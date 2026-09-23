"""Mineru PDF Loader

This loader uploads a PDF to the Mineru API, receives a ZIP package
with parsed outputs (Markdown/text/images), extracts the archive,
builds a `Document` with Markdown text and image placeholders, and
stores images under `data/images/{doc_hash}/`.

Configuration:
- `api_url`: Mineru API endpoint (defaults to environment MINERU_API_URL)
- `api_key`: Mineru API key (defaults to environment MINERU_API_KEY)
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

try:
    import requests
except Exception:  # pragma: no cover - requests may be missing in some envs
    requests = None

from src.core.types import Document
from src.libs.loader.base_loader import BaseLoader

logger = logging.getLogger(__name__)


class MineruPdfLoader(BaseLoader):
    """Loader that uses Mineru's PDF parsing API and adapts output.

    Notes:
    - Expects Mineru to return a ZIP file containing at least one
      Markdown/JSON/text output and optionally images.
    - Saves images to `image_storage_dir / {doc_hash}/` and inserts
      placeholders in the Markdown text like `[IMAGE: {image_id}]`.
    - `timeout` is a local HTTP client timeout for `requests`, not a
      MinerU API request field.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 1800,
        extract_images: bool = True,
        image_storage_dir: str | Path = "data/images",
        model_version: str = "vlm",
        poll_interval: int = 5,
    ):
        if requests is None:
            raise ImportError("requests is required for MineruPdfLoader")

        # Handle both formats: "https://mineru.net" or "https://mineru.net/api/v4"
        api_url = (api_url or "https://mineru.net").rstrip("/")
        if api_url.endswith("/api/v4"):
            # Already includes /api/v4, use as-is
            base_api_url = api_url
        else:
            # Add /api/v4 if not present
            base_api_url = f"{api_url}/api/v4"
        
        self.api_base_url = base_api_url
        self.upload_batch_url = f"{base_api_url}/file-urls/batch"
        self.batch_result_url = f"{base_api_url}/extract-results/batch/{{batch_id}}"
        self.api_key = api_key
        self.timeout = timeout
        self.extract_images = extract_images
        self.image_storage_dir = Path(image_storage_dir)
        self.model_version = model_version
        self.poll_interval = poll_interval
        
        # Log final configuration
        logger.debug(f"MineruPdfLoader initialized: api_url={base_api_url}, model={model_version}")

    def load(self, file_path: str | Path) -> Document:
        path = self._validate_file(file_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"File is not a PDF: {path}")

        # compute doc hash and doc id
        doc_hash = self._compute_file_hash(path)
        doc_id = f"doc_{doc_hash[:16]}"

        # call mineru api and get zip bytes
        zip_bytes = self._call_mineru_api(path, doc_hash)

        # extract zip to temp dir
        tmpdir = Path(tempfile.mkdtemp(prefix="mineru_") )
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
                z.extractall(tmpdir)

            # find a markdown/text output
            text = self._find_parsed_text(tmpdir)

            images_meta: List[Dict[str, Any]] = []
            if self.extract_images:
                images_meta = self._process_images_from_dir(
                    tmpdir, doc_hash
                )

                # insert placeholders if not already present
                text = self._insert_placeholders(text, images_meta)

            metadata: Dict[str, Any] = {
                "source_path": str(path),
                "doc_type": "pdf",
                "doc_hash": doc_hash,
                "source": "mineru",
            }
            if images_meta:
                metadata["images"] = images_meta

            return Document(id=doc_id, text=text, metadata=metadata)

        finally:
            # cleanup temp dir
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                logger.debug(f"Failed to remove tempdir: {tmpdir}")

    def _call_mineru_api(self, pdf_path: Path, doc_hash: str) -> bytes:
        """Upload PDF to MinerU using the official batch file upload flow and return ZIP bytes.

        The MinerU API request body follows official docs:
        - POST /api/v4/file-urls/batch with JSON {files:[...], model_version:...}
        - then PUT the PDF to the returned upload URL
        - then poll /api/v4/extract-results/batch/{batch_id}

        Note: `timeout` is used only for local HTTP calls and is not sent as
        part of the MinerU JSON payload.
        """
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data_id = f"mineru_{doc_hash[:16]}"
        payload = {
            "files": [{"name": pdf_path.name, "data_id": data_id}],
            "model_version": self.model_version,
        }

        resp = requests.post(
            self.upload_batch_url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Mineru batch upload request failed: HTTP {resp.status_code}. Response: {resp.text}")

        try:
            result = resp.json()
        except Exception as e:
            raise RuntimeError(f"Mineru batch upload returned invalid JSON: {e}. Response: {resp.text}")

        code = result.get("code")
        if code != 0:
            msg = result.get("msg", "Unknown error")
            raise RuntimeError(f"Mineru batch upload API error (code={code}): {msg}")

        batch_data = result.get("data")
        if not batch_data:
            raise RuntimeError(f"Mineru batch upload response missing 'data' field: {result}")

        batch_id = batch_data.get("batch_id")
        file_urls = batch_data.get("file_urls") or []
        if not batch_id:
            raise RuntimeError(f"Mineru response missing batch_id: {batch_data}")
        if not file_urls:
            raise RuntimeError(f"Mineru response missing file_urls: {batch_data}")

        upload_url = file_urls[0]
        logger.info(f"Got batch_id={batch_id}, uploading PDF to: {upload_url[:50]}...")
        with open(pdf_path, "rb") as f:
            upload_resp = requests.put(upload_url, data=f, timeout=self.timeout)

        if upload_resp.status_code not in (200, 201):
            raise RuntimeError(f"Mineru file upload PUT failed: HTTP {upload_resp.status_code}. Response: {upload_resp.text[:200]}")

        logger.info(f"PDF uploaded successfully, polling batch_id={batch_id} for extraction...")
        return self._poll_batch_result(batch_id)

    def _poll_batch_result(self, batch_id: str) -> bytes:
        """Poll MinerU for extraction result until done or failed."""
        deadline = time.time() + self.timeout
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        poll_count = 0
        while True:
            if time.time() > deadline:
                raise RuntimeError(f"Mineru batch extraction timed out after {self.timeout}s (polled {poll_count} times)")

            resp = requests.get(
                self.batch_result_url.format(batch_id=batch_id),
                headers=headers,
                timeout=self.timeout,
            )

            if resp.status_code != 200:
                raise RuntimeError(f"Mineru batch result query failed: HTTP {resp.status_code}. Response: {resp.text[:200]}")

            try:
                result = resp.json()
            except Exception as e:
                raise RuntimeError(f"Mineru batch result returned invalid JSON: {e}. Response: {resp.text[:200]}")

            code = result.get("code")
            if code != 0:
                msg = result.get("msg", "Unknown error")
                raise RuntimeError(f"Mineru batch result API error (code={code}): {msg}")

            batch_data = result.get("data")
            if not batch_data:
                raise RuntimeError(f"Mineru batch result missing 'data' field: {result}")

            extract_result = batch_data.get("extract_result")
            if not isinstance(extract_result, list):
                raise RuntimeError(f"Mineru batch result 'extract_result' is not a list: {extract_result}")
            
            if not extract_result:
                # No results yet, keep polling
                poll_count += 1
                logger.debug(f"Poll #{poll_count}: extract_result is empty, waiting...")
                time.sleep(self.poll_interval)
                continue

            item = extract_result[0]
            state = item.get("state")
            poll_count += 1
            logger.info(f"Poll #{poll_count}: state={state}")

            if state == "done":
                zip_url = item.get("full_zip_url")
                if not zip_url:
                    raise RuntimeError(f"Mineru batch result missing full_zip_url: {item}")
                logger.info(f"Extraction done, downloading ZIP from: {zip_url[:50]}...")
                return self._download_zip(url=zip_url, headers=headers)

            if state == "failed":
                err_msg = item.get("err_msg", "Unknown error")
                raise RuntimeError(f"Mineru extraction failed: {err_msg}")

            # Other states: pending, running, waiting-file, converting
            logger.debug(f"Extraction in progress (state={state}), continuing to poll...")
            time.sleep(self.poll_interval)

    def _download_zip(self, url: str, headers: Dict[str, str]) -> bytes:
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download Mineru zip from {url}: {resp.status_code} {resp.text}")
        return resp.content

    def _find_parsed_text(self, extracted_dir: Path) -> str:
        """Locate a textual output (Markdown/JSON/TXT) and return text.

        Per MinerU official docs, priority order:
        1. full.md (standard MinerU output for Markdown)
        2. Other .md files
        3. .txt files
        4. .json files with text content
        """
        # Priority 1: Look for full.md (official MinerU output)
        full_md = extracted_dir / "full.md"
        if full_md.exists() and full_md.is_file():
            text = full_md.read_text(encoding="utf-8")
            logger.info(f"Extracted text from official full.md ({len(text)} bytes)")
            return text

        # Priority 2: Look for any other .md files
        md_files = list(extracted_dir.glob("**/*.md"))
        if md_files:
            md_path = md_files[0]
            text = md_path.read_text(encoding="utf-8")
            logger.info(f"Extracted text from {md_path.name} ({len(text)} bytes)")
            return text

        # Priority 3: Look for .txt files
        txt_files = list(extracted_dir.glob("**/*.txt"))
        if txt_files:
            text = txt_files[0].read_text(encoding="utf-8")
            logger.info(f"Extracted text from {txt_files[0].name} ({len(text)} bytes)")
            return text

        # Priority 4: Look for structured JSON outputs (line-and-span structure per docs)
        json_files = list(extracted_dir.glob("**/*.json"))
        for jf in json_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                continue

            # MinerU line-and-span structure (from output_files docs)
            if isinstance(data.get("lines"), list):
                try:
                    text_parts = []
                    for line in data.get("lines", []):
                        if isinstance(line, dict) and "text" in line:
                            text_parts.append(line["text"])
                        elif isinstance(line, str):
                            text_parts.append(line)
                    if text_parts:
                        text = "\n".join(text_parts)
                        logger.info(f"Extracted text from {jf.name} (lines structure, {len(text)} bytes)")
                        return text
                except Exception:
                    pass

            # pages array
            if isinstance(data.get("pages"), list):
                parts = []
                for p in data.get("pages", []):
                    if isinstance(p, dict) and "text" in p:
                        parts.append(p["text"])
                    elif isinstance(p, str):
                        parts.append(p)
                if parts:
                    text = "\n\n".join(parts)
                    logger.info(f"Extracted text from {jf.name} (pages structure, {len(text)} bytes)")
                    return text

            # fallback: common text keys
            for key in ("text", "content", "markdown"):
                if key in data and isinstance(data[key], str):
                    text = data[key]
                    logger.info(f"Extracted text from {jf.name} (key='{key}', {len(text)} bytes)")
                    return text

        raise RuntimeError("mineru zip contains no parsable text output (.md/.txt/.json with text)")

    def _process_images_from_dir(self, extracted_dir: Path, doc_hash: str) -> List[Dict[str, Any]]:
        """Collect image files from extracted dir, save to image_storage_dir and return metadata list."""
        images_meta: List[Dict[str, Any]] = []
        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

        target_dir = self.image_storage_dir / doc_hash
        target_dir.mkdir(parents=True, exist_ok=True)

        idx = 0
        for img_path in sorted(extracted_dir.glob("**/*")):
            if img_path.suffix.lower() in image_extensions and img_path.is_file():
                idx += 1
                try:
                    original_src = img_path.relative_to(extracted_dir).as_posix()
                except ValueError:
                    original_src = img_path.name

                image_id = self._generate_mineru_image_id(doc_hash, original_src, idx)
                dest_name = f"{image_id}{img_path.suffix.lower()}"
                dest_path = target_dir / dest_name
                try:
                    shutil.copyfile(img_path, dest_path)
                except Exception as e:
                    logger.warning(f"Failed to copy image {img_path}: {e}")
                    continue

                # record metadata; page/position unknown from mineru output
                try:
                    relative = dest_path.relative_to(Path.cwd())
                except Exception:
                    relative = dest_path.absolute()

                meta = {
                    "id": image_id,
                    "path": str(relative),
                    "original_src": original_src,
                    "original_name": img_path.name,
                    "page": None,
                    "text_offset": None,
                    "text_length": len(f"[IMAGE: {image_id}]") ,
                    "position": {},
                }
                images_meta.append(meta)

        return images_meta

    def _insert_placeholders(self, text: str, images_meta: List[Dict[str, Any]]) -> str:
        """Insert placeholders for images into the markdown text.

        Strategy:
        - If the markdown already references an image filename, replace that occurrence with placeholder.
        - Otherwise append placeholders at the end of the document in order.
        Also fill `text_offset` for each image metadata when possible.
        """
        if not images_meta:
            return text

        md_img_re = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
        html_img_re = re.compile(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)

        matches = []  # list of (start, end, src)
        for m in md_img_re.finditer(text):
            matches.append((m.start(), m.end(), m.group(1)))
        for m in html_img_re.finditer(text):
            matches.append((m.start(), m.end(), m.group(1)))

        used_meta_ids = set()
        replacements = []
        for s, e, src in matches:
            matched_meta = self._find_image_meta_for_src(src, images_meta, used_meta_ids)
            if matched_meta is None:
                continue

            placeholder = f"[IMAGE: {matched_meta['id']}]"
            replacements.append((s, e, placeholder, matched_meta))
            used_meta_ids.add(matched_meta["id"])

        for s, e, placeholder, meta in sorted(replacements, key=lambda item: item[0], reverse=True):
            text = text[:s] + placeholder + text[e:]
            meta["text_offset"] = s
            meta["text_length"] = len(placeholder)

        lowered = text.lower()
        for meta in images_meta:
            if meta["id"] in used_meta_ids:
                continue

            placeholder = f"[IMAGE: {meta['id']}]"
            candidates = [
                meta.get("original_src", ""),
                meta.get("original_name", ""),
                Path(meta.get("path", "")).name,
            ]
            pos = -1
            token = ""
            for candidate in candidates:
                candidate = candidate.strip()
                if not candidate:
                    continue
                pos = lowered.find(candidate.lower())
                token = candidate
                if pos != -1:
                    break

            if pos != -1:
                text = text[:pos] + placeholder + text[pos + len(token):]
                meta["text_offset"] = pos
                meta["text_length"] = len(placeholder)
                lowered = text.lower()
                continue

            insert_position = len(text)
            if not text.endswith("\n"):
                text += "\n"
            text += f"{placeholder}\n"
            meta["text_offset"] = insert_position
            meta["text_length"] = len(placeholder)

        return text

    @staticmethod
    def _generate_mineru_image_id(doc_hash: str, original_src: str, sequence: int) -> str:
        src_hash = hashlib.sha1(original_src.encode("utf-8")).hexdigest()[:10]
        return f"{doc_hash[:8]}_{src_hash}_{sequence}"

    @classmethod
    def _find_image_meta_for_src(
        cls,
        src: str,
        images_meta: List[Dict[str, Any]],
        used_meta_ids: set,
    ) -> Optional[Dict[str, Any]]:
        src_norm = cls._normalize_image_src(src)
        if not src_norm:
            return None

        for meta in images_meta:
            if meta.get("id") in used_meta_ids:
                continue

            candidates = [
                meta.get("original_src", ""),
                meta.get("original_name", ""),
                Path(meta.get("path", "")).name,
            ]
            for candidate in candidates:
                candidate_norm = cls._normalize_image_src(candidate)
                if not candidate_norm:
                    continue
                if src_norm == candidate_norm:
                    return meta
                if src_norm.endswith(f"/{candidate_norm}") or candidate_norm.endswith(f"/{src_norm}"):
                    return meta
                if Path(src_norm).name == Path(candidate_norm).name:
                    return meta

        return None

    @staticmethod
    def _normalize_image_src(src: str) -> str:
        src = (src or "").strip()
        if not src:
            return ""

        if src.startswith("<") and src.endswith(">"):
            src = src[1:-1].strip()
        else:
            src = src.split()[0].strip("'\"")

        parsed = urlparse(src)
        if parsed.scheme in ("http", "https"):
            src = parsed.path
        else:
            src = src.split("#", 1)[0].split("?", 1)[0]

        src = unquote(src).replace("\\", "/").strip()
        while src.startswith("./"):
            src = src[2:]
        return src.lower()

    def _compute_file_hash(self, file_path: Path) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def _generate_image_id(doc_hash: str, page: int, sequence: int) -> str:
        return f"{doc_hash[:8]}_{page}_{sequence}"

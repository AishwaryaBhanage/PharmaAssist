"""Source pages and figure crops behind citations, for signed-in users only:

  GET /api/v1/sources/{doc_id}/p{N}.pdf   one page of the document's active version
  GET /api/v1/figures/{doc_id}/{name}     a figure crop indexed on one of its pages

With object storage configured the response is a 302 to a short-lived presigned URL (`#page=N` for
the PDF, so the browser opens the page); in development the local copy under docs/ (one page copied
out with PyMuPDF) or storage/figures/ is served. Pages are checked against the catalog's page count
and figure names against `store.content`, so nothing outside the indexed corpus is reachable.

Browsers can't add an Authorization header to a link or <img>, so these two routes also accept the
access token as `?access_token=`; everything else is Bearer-only.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.auth import bearer_token, user_from_token
from app.citations import crop_name
from app.deps import API, Deps, get_deps
from app.errors import not_found
from pharmassist.store.protocols import User

router = APIRouter(prefix=API, tags=["sources"])
DOC_ID = re.compile(r"^[a-z0-9_]{1,80}$")
PAGE_FILE = re.compile(r"^p(\d{1,4})\.pdf$")
FIGURE_FILE = re.compile(r"^p\d{3}_f\d{1,3}\.png$")
NO_STORE = {"Cache-Control": "no-store"}


def link_user(request: Request, access_token: str | None = Query(default=None),
              deps: Deps = Depends(get_deps)) -> User:
    return user_from_token(bearer_token(request) or access_token, deps)


def _docs_dir(deps: Deps):
    if deps.docs_dir is not None:
        return deps.docs_dir
    from pharmassist.catalog import docs_dir
    return docs_dir()


@router.get("/sources/{doc_id}/{name}", response_class=Response)
def source_page(doc_id: str, name: str, user: User = Depends(link_user), deps: Deps = Depends(get_deps)):
    m = PAGE_FILE.match(name)
    if not (DOC_ID.match(doc_id) and m):
        raise not_found("No such source page.")
    n = int(m.group(1))
    entry = deps.store.documents.catalog().get(doc_id)
    doc = deps.store.documents.get_document(doc_id)
    version = deps.store.documents.get_version(doc.active_version_id) if doc and doc.active_version_id else None
    if not entry or version is None or not str(entry.get("file", "")).endswith(".pdf"):
        raise not_found("No such source page.")
    pages = version.pages or entry.get("pages") or 0
    if pages and not 1 <= n <= pages:
        raise not_found("No such source page.")
    url = deps.storage.presign(version.s3_key, content_type="application/pdf", fragment=f"page={n}")
    if url:
        return RedirectResponse(url, status_code=302, headers=NO_STORE)
    path = _docs_dir(deps) / entry["file"]
    if not path.exists():
        raise not_found("No such source page.")
    import pymupdf
    with pymupdf.open(path) as src:
        if not 1 <= n <= src.page_count:
            raise not_found("No such source page.")
        out = pymupdf.open()
        out.insert_pdf(src, from_page=n - 1, to_page=n - 1)
        data = out.tobytes(garbage=3, deflate=True)
        out.close()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{doc_id}_p{n}.pdf"',
                             "Cache-Control": "private, max-age=86400"})


@router.get("/figures/{doc_id}/{name}", response_class=Response)
def figure_crop(doc_id: str, name: str, user: User = Depends(link_user), deps: Deps = Depends(get_deps)):
    if not (DOC_ID.match(doc_id) and FIGURE_FILE.match(name)):
        raise not_found("No such figure.")
    page = int(name[1:4])
    figure = next((f for f in deps.store.content.figures_for_page(doc_id, page) if crop_name(f) == name), None)
    if figure is None:
        raise not_found("No such figure.")
    url = deps.storage.presign(figure.crop_s3_key, content_type="image/png") if figure.crop_s3_key else None
    if url:
        return RedirectResponse(url, status_code=302, headers=NO_STORE)
    path = deps.figures_dir / doc_id / name
    if not path.exists():
        raise not_found("No such figure.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

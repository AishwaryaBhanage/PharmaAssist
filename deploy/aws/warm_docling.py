"""Download Docling's models at image build time: convert a generated one-page PDF that has text, a
table-like grid and an image, with the pipeline options of pharmassist.parsers.docling_parser._converter
(repeated here so this layer doesn't depend on the project code and stays cached)."""
import pymupdf
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def _converter():
    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.do_table_structure = True
    opts.do_picture_classification = True
    opts.generate_picture_images = True
    opts.images_scale = 2
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


doc = pymupdf.open()
page = doc.new_page()
page.insert_text((72, 72), "Warm-up page: Table 1. Doses", fontsize=12)
for i in range(4):
    for j in range(3):
        page.draw_rect(pymupdf.Rect(72 + j * 120, 100 + i * 24, 192 + j * 120, 124 + i * 24))
        page.insert_text((76 + j * 120, 116 + i * 24), f"r{i}c{j}", fontsize=10)
pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 120), False)
pix.clear_with(200)
page.insert_image(pymupdf.Rect(72, 260, 272, 380), pixmap=pix)
page.insert_text((80, 320), "Box 1 -> Box 2", fontsize=12)
doc.save("/tmp/warm.pdf")
_converter().convert("/tmp/warm.pdf")
print("docling models ready")

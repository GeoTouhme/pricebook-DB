"""Local, bounded OCR for image PDFs. No documents leave the server."""
import csv
import io
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from PIL import Image, ImageOps

MAX_SCAN_PAGES = 5
MAX_PIXELS = 20_000_000


class OCRUnavailable(ValueError):
    pass


def scan_page(page):
    return bool(page.images) and sum(c.isalnum() for c in (page.extract_text() or '')) < 50


def page_image(page):
    if len(page.images) == 1:
        source = page.images[0]
        size = source.get('srcsize', (0,0))
        if size[0]*size[1] > MAX_PIXELS:
            raise ValueError('Scanned page exceeds the 20 megapixel limit. Reduce its resolution.')
        try:
            image = Image.open(io.BytesIO(source['stream'].get_data()))
            if image.width*image.height>MAX_PIXELS:
                raise OCRUnavailable('Scanned page exceeds the 20 megapixel limit.')
            image.load()
            return image.convert('L')
        except OCRUnavailable:raise
        except (OSError, ValueError):
            pass
    if math.ceil(page.width*2.5)*math.ceil(page.height*2.5)>MAX_PIXELS:
        raise ValueError('Scanned page exceeds the OCR image limit. Reduce its page size.')
    image = page.to_image(resolution=180).original.convert('L')
    if image.width*image.height > MAX_PIXELS:
        raise ValueError('Scanned page exceeds the OCR image limit.')
    return image


def orient(image, folder, env):
    # OSD is especially useful for the sideways receipt continuation in a PDF.
    preview = image.copy();preview.thumbnail((4000,4000))
    path=Path(folder)/'orientation.png';preview.save(path)
    try:
        result=subprocess.run(['tesseract',str(path),'stdout','--psm','0'],capture_output=True,text=True,env=env,timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise OCRUnavailable('OCR orientation timed out. Split the document or reduce its resolution.') from exc
    rotation=re.search(r'Rotate:\s*(0|90|180|270)\b',result.stdout)
    confidence=re.search(r'Orientation confidence:\s*([\d.]+)',result.stdout)
    proposed=int(rotation[1]) if rotation else 0
    threshold=1 if proposed in (90,270) and image.width>image.height*1.5 else 5
    degrees=proposed if confidence and float(confidence[1])>=threshold else 0
    if degrees:
        image=image.rotate(-degrees,expand=True)
    return image,degrees


def read_pass(path, prefix, mode, env):
    try:
        result=subprocess.run(['tesseract',str(path),str(prefix),'-l','eng','--psm',str(mode),
                               'tsv','txt','makebox'],capture_output=True,text=True,env=env,timeout=40)
    except subprocess.TimeoutExpired as exc:
        raise OCRUnavailable('OCR page processing exceeded 40 seconds. Split the document or reduce its resolution.') from exc
    if result.returncode:
        raise OCRUnavailable('Local OCR could not run. Install tesseract-ocr and its English language data, then restart the dashboard.')
    words=[]
    with prefix.with_suffix('.tsv').open() as file:
        for row in csv.DictReader(file,delimiter='\t',quoting=csv.QUOTE_NONE):
            if not row['text'].strip():continue
            words.append(dict(text=row['text'],x0=int(row['left']),x1=int(row['left'])+int(row['width']),
                top=int(row['top']),bottom=int(row['top'])+int(row['height']),confidence=float(row['conf'])))
    chars=[]
    for row in prefix.with_suffix('.box').read_text().splitlines():
        parts=row.rsplit(' ',5)
        if len(parts)!=6:continue
        char,left,bottom,right,top,_=parts
        # Box coordinates are bottom-up; dimensions come from the working image.
        chars.append(dict(text=char,x0=int(left),x1=int(right),raw_top=int(top),raw_bottom=int(bottom)))
    return dict(text=prefix.with_suffix('.txt').read_text(),words=words,chars=chars)


def ocr_pages(pdf):
    if not shutil.which('tesseract'):
        raise OCRUnavailable('This is a scanned PDF. On Ubuntu install: sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd. Then restart Streamlit.')
    if len(pdf.pages)>MAX_SCAN_PAGES:
        raise ValueError('Upload at most 5 scanned pages at a time.')
    pages=[]
    env=dict(os.environ,OMP_THREAD_LIMIT='1')
    base=os.environ.get('PRICEBOOK_PDF_WORKDIR')
    with tempfile.TemporaryDirectory(prefix='scan-',dir=base) as directory:
        for index,page in enumerate(pdf.pages,1):
            if not scan_page(page):
                pages.append(dict(text=page.extract_text() or '',words=page.extract_words(),chars=page.chars,
                                  width=page.width,height=page.height,rotation=0,page=index,scanned=False));continue
            image,rotation=orient(page_image(page),directory,env)
            scale=min(4,1800/image.width,14000/image.height,math.sqrt(MAX_PIXELS/(image.width*image.height)))
            image=ImageOps.autocontrast(image.resize((round(image.width*scale),round(image.height*scale))))
            path=Path(directory)/f'page-{index}.png';image.save(path)
            primary=read_pass(path,Path(directory)/f'page-{index}-4',4,env)
            secondary=read_pass(path,Path(directory)/f'page-{index}-6',6,env)
            for result in (primary,secondary):
                for char in result['chars']:
                    char['top']=image.height-char.pop('raw_top');char['bottom']=image.height-char.pop('raw_bottom')
            # Decode graphics as an independent source; OCR text never repairs a barcode.
            import zxingcpp
            barcodes=[]
            for code in zxingcpp.read_barcodes(image):
                if not code.valid or str(code.format) not in ('BarcodeFormat.UPCA','BarcodeFormat.EAN13','BarcodeFormat.UPCE'):continue
                position=code.position
                points=[position.top_left,position.top_right,position.bottom_left,position.bottom_right]
                barcodes.append(dict(text=code.text,format=str(code.format),top=min(p.y for p in points),
                                     bottom=max(p.y for p in points),x0=min(p.x for p in points),x1=max(p.x for p in points)))
            pages.append(dict(**primary,alternate_text=secondary['text'],alternate_words=secondary['words'],
                alternate_chars=secondary['chars'],barcodes=barcodes,width=image.width,height=image.height,
                rotation=rotation,page=index,scanned=True))
    return pages

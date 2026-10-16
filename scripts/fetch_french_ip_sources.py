"""Fetch two allowlisted public French law PDFs linked by their official WIPO records."""
import hashlib
import html
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlparse

import pymupdf

ROOT=Path(__file__).resolve().parents[1]
SOURCES=[("3819","tn001","tn001fr_wipo.pdf","Brevets — Loi n° 2000-84 — version française fournie","Loi n° 2000-84"),
         ("3832","tn014","tn014fr_wipo.pdf","Marques — Loi n° 2001-36 — version française fournie","Loi n° 2001-36")]

if __name__=="__main__":
    folder=ROOT/"law/TUNISIA_LEGAL_BUSINESS_CORPUS/08_INTELLECTUAL_PROPERTY"
    folder.mkdir(parents=True,exist_ok=True)
    for record,prefix,name,title,act in SOURCES:
        target=folder/name
        if target.is_file() and target.with_name(name+'.meta.json').is_file():
            print("Already supplied:",name,flush=True)
            continue
        record_url=f"https://www.wipo.int/wipolex/en/legislation/details/{record}"
        with urllib.request.urlopen(record_url,timeout=15) as response:
            page=html.unescape(response.read(3*1024*1024).decode('utf-8'))
        urls=list(dict.fromkeys(re.findall(r'https://wipolex-res\.wipo\.int/edocs/lexdocs/laws/fr/tn/'+prefix+r'fr[^\s\'"<>]*?\.pdf(?:\?[^\s\'"<>]*)?',page)))
        urls.sort(key=lambda value:'?' in value,reverse=True)
        if not urls:
            raise RuntimeError("Official record does not expose the expected French PDF: "+record)
        last_error=None
        for url in urls[:2]:
            try:
                with urllib.request.urlopen(url,timeout=20) as response:
                    raw=response.read(3*1024*1024+1)
                if len(raw)>3*1024*1024 or not raw.startswith(b'%PDF'):
                    raise ValueError("Unexpected French law response")
                with pymupdf.open(stream=raw,filetype='pdf') as pdf:
                    if not 1<=len(pdf)<=100: raise ValueError("Unexpected page count")
                target.write_bytes(raw)
                metadata={'name':title,'lang':'fr','jurisdiction':'TN','source_kind':'legislation','act':act,
                          'article_numbering':'bare',
                          'url':record_url,'current_version_verified':False,'sha256':hashlib.sha256(raw).hexdigest(),
                          'provenance':'Public French legislation PDF linked from the allowlisted official WIPO Lex record'}
                target.with_name(name+'.meta.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
                print("Fetched public legislation:",name,len(raw),flush=True)
                break
            except (OSError,ValueError,RuntimeError) as error:
                last_error=type(error).__name__
        else:
            raise RuntimeError("Unable to read the official French PDF: "+record+' ('+str(last_error)+')')

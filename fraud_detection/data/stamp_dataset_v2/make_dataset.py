#!/usr/bin/env python3
"""Synthetic stamp-pair dataset generator (fictitious issuer BMC, stamp reads SPECIMEN / FAUX).
Classes: reference (fixed stamp spec) vs counterfeit (reference + 1-4 randomized mutations).
Scan-style augmentation is applied identically to both classes so it cannot be used as a shortcut.
Usage: python make_dataset.py --n 100 --out dataset --seed 42 --dpi 120
"""
import argparse, copy, csv, io, json, math, os, random, subprocess, tempfile
import numpy as np
from PIL import Image, ImageFilter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import Color, black, HexColor
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
import arabic_reshaper
from bidi.algorithm import get_display

LIB="/usr/share/fonts/truetype/liberation/"; DJV="/usr/share/fonts/truetype/dejavu/"
for n,f in [("Ser","LiberationSerif-Regular"),("Ser-B","LiberationSerif-Bold"),("Ser-I","LiberationSerif-Italic"),("Ser-BI","LiberationSerif-BoldItalic"),
            ("LSans-B","LiberationSans-Bold"),("LSans","LiberationSans-Regular")]:
    pdfmetrics.registerFont(TTFont(n,LIB+f+".ttf"))
for n,f in [("Ar","DejaVuSans"),("Ar-B","DejaVuSans-Bold"),("DVS-B","DejaVuSerif-Bold"),("DVS","DejaVuSerif")]:
    pdfmetrics.registerFont(TTFont(n,DJV+f+".ttf"))
pdfmetrics.registerFontFamily("Ser",normal="Ser",bold="Ser-B",italic="Ser-I",boldItalic="Ser-BI")
def ar(s): return get_display(arabic_reshaper.reshape(s))

REF=dict(fonts=["Ser-B","Ser-B","Ser-B","Ser","Ser-B"], sizes=[11,9,12,8,8.5], cs=[0,0,0,0,0],
         base=[26,11,-5,-19,-31], rot=-3.0, dx=0.0, dy=0.0, ink=[0.10,0.22,0.68], alpha=0.84,
         accents=[True,True,True,True,True], dash="-")
ALT_FONTS={"Ser-B":["DVS-B","LSans-B","Ser-BI"],"Ser":["DVS","LSans","Ser-I"]}

def stamp_lines(p):
    a=p["accents"]
    return ["BMC %s AGENCE LAC 2"%p["dash"],
            "VU ET CERTIFIÉ SINCÈRE" if a[1] else "VU ET CERTIFIE SINCERE",
            "LE 11 MARS 2024","BANQUE FICTIVE",
            "SPÉCIMEN / FAUX" if a[4] else "SPECIMEN / FAUX"]

def build_page(path,p):
    W,H=A4; L,R=62,W-62
    c=canvas.Canvas(path,pagesize=A4); c.setTitle("Attestation de solde bancaire - SPECIMEN")
    def T(x,y,s,f="Ser",sz=9,col=black,al="l"):
        c.setFont(f,sz);c.setFillColor(col)
        {"l":c.drawString,"r":c.drawRightString,"c":c.drawCentredString}[al](x,H-y,s)
    T(L,70,"BANQUE MÉDITERRANÉENNE DU COMMERCE (BMC)","Ser-B",10)
    T(L,84,"Société Anonyme");T(L,97,"Agence Les Berges du Lac 2");T(L,110,"Service Entreprises & Startups","Ser",8)
    c.setFillColor(black);c.setFont("Ar-B",9.5);c.drawRightString(R,H-70,ar("البنك المتوسطي للتجارة"))
    c.setFont("Ar",8);c.drawRightString(R,H-84,ar("شركة خفية الاسم"));c.drawRightString(R,H-97,ar("وكالة صفاقس"))
    c.setFont("Ar",7);c.drawRightString(R,H-110,ar("مصلحة المؤسسات والمؤسسات الناشئة"))
    T(L,145,"N/Réf : ","Ser-B",9);T(L+34,145,"BMC/2024/AS-03317")
    T(W/2-20,145,"Agence : ","Ser-B",9);T(W/2+20,145,"Lac 2 (0412)")
    T(R,145,"Tunis, le : 08 Mars 2024","Ser",9,black,"r")
    T(W/2,185,"ATTESTATION DE SOLDE BANCAIRE","Ser-B",15,black,"c")
    c.setLineWidth(1);c.line(W/2-125,H-189,W/2+125,H-189)
    T(W/2,202,"« COMPTE ENTREPRISE - STARTUP »","Ser-B",9,black,"c")
    body=ParagraphStyle("b",fontName="Ser",fontSize=9.5,leading=17,alignment=TA_JUSTIFY,firstLineIndent=22)
    txt=("Nous soussignés, Banque Méditerranéenne du Commerce, agence Les Berges du Lac 2, attestons par la présente que la société "
         "ci-après désignée est titulaire d'un compte ouvert dans nos livres et présentait, à la date du 08 Mars 2024, la situation suivante :")
    pp=Paragraph(txt,body);w,h=pp.wrap(R-L,300);pp.drawOn(c,L,H-218-h)
    rows=[["Titulaire du Compte","NOVA MEDTECH S.A.R.L"],["Identifiant Unique / RNE","1832016 D/M/000 (Registre National des Entreprises : 77410/209/36)"],
      ["Nature du Compte","Compte courant professionnel en dinars tunisiens"],["Date d'Ouverture","15 Mars 2024"],["RIB","12 045 0093821740655 28"],
      ["IBAN","TN59 1204 5009 3821 7406 5528"],["Solde Créditeur","120 000,000 DT (cent deux mille dinars tunisiens)"]]
    st=ParagraphStyle("c",fontName="Ser",fontSize=9.5,leading=12);sb=ParagraphStyle("cb",parent=st,fontName="Ser-B")
    t=Table([[Paragraph(a,sb),Paragraph(b,st)] for a,b in rows],colWidths=[130,R-L-130])
    t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,black),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),("LEFTPADDING",(0,0),(-1,-1),8)]))
    tw,th=t.wrap(R-L,400);ty=H-218-h-18-th;t.drawOn(c,L,ty)
    y=H-ty+22;T(L,y,"Mentions :","Ser-B",9)
    small=ParagraphStyle("s",fontName="Ser",fontSize=9,leading=13,alignment=TA_JUSTIFY)
    for s_ in ["• La présente attestation est délivrée à la demande de l'intéressé, sans engagement de notre part, pour servir et valoir ce que de droit. Elle est valable trois (3) mois à compter de sa date de délivrance.",
               "• Elle ne constitue en aucun cas une garantie de financement ni un engagement de crédit."]:
        q=Paragraph(s_,small);pw,ph=q.wrap(R-L,100);y+=6;q.drawOn(c,L,H-y-ph);y+=ph
    y+=32
    T(L,y,"Le Chargé de Clientèle Entreprises,","Ser",9.5);T(R-170,y,"Pour la Banque et par délégation,","Ser-B",9.5)
    T(L+8,y+26,"M. Jebali","Ser-I",13)
    # ---- stamp ----
    cx,cy=R-100+p["dx"],H-(y+52)+p["dy"]
    c.saveState();c.translate(cx,cy);c.rotate(p["rot"])
    c.setFillColor(Color(*p["ink"],alpha=p["alpha"]))
    for i,s in enumerate(stamp_lines(p)):
        f,z,cs=p["fonts"][i],p["sizes"][i],p["cs"][i]
        wd=stringWidth(s,f,z)+cs*len(s)
        o=c.beginText();o.setFont(f,z);o.setCharSpace(cs);o.setTextOrigin(-wd/2,p["base"][i]);o.textOut(s);c.drawText(o)
    c.restoreState()
    c.setStrokeColor(black);c.setLineWidth(.8);c.line(L,58,R,58)
    T(L,H-45,"BMC - S.A. au capital de 150 000 000 DT - Réf. interne : BMC/2024/AS-03371","Ser",8,HexColor("#444444"))
    T(R,H-45,"Page 1 / 1","Ser",8,HexColor("#444444"),"r")
    c.save()
    return y+52  # stamp centre, points from top

# ---- mutations: each returns (name, detail) and edits p in place ----
def m_size(p,r,m):
    i=r.randrange(5);d=r.choice([-1,1])*r.uniform(.3,.8)*m;p["sizes"][i]=round(p["sizes"][i]+d,2);return "size",f"line{i+1} {d:+.2f}pt"
def m_spacing(p,r,m):
    i=r.randrange(5);d=r.uniform(.15,.4)*m;p["cs"][i]=round(d,3);return "letter_spacing",f"line{i+1} +{d:.2f}pt"
def m_font(p,r,m):
    i=r.randrange(5);alt=r.choice(ALT_FONTS[REF["fonts"][i]]);p["fonts"][i]=alt;return "font_substitution",f"line{i+1} {REF['fonts'][i]}->{alt}"
def m_accent(p,r,m):
    i=r.choice([1,4]);p["accents"][i]=False;return "dropped_accents",f"line{i+1}"
def m_base(p,r,m):
    i=r.randrange(5);d=r.choice([-1,1])*r.uniform(.8,2.2)*m;p["base"][i]=round(p["base"][i]+d,2);return "baseline_shift",f"line{i+1} {d:+.2f}pt"
def m_rot(p,r,m):
    d=r.choice([-1,1])*r.uniform(.7,2.0)*m;p["rot"]=round(p["rot"]+d,2);return "rotation",f"{d:+.2f}deg"
def m_off(p,r,m):
    dx,dy=[r.choice([-1,1])*r.uniform(1,4)*m for _ in range(2)];p["dx"],p["dy"]=round(dx,2),round(dy,2);return "offset",f"dx{dx:+.2f} dy{dy:+.2f}pt"
def m_ink(p,r,m):
    p["ink"]=[round(min(1,max(0,v+r.choice([-1,1])*r.uniform(.02,.06)*m)),3) for v in p["ink"]]
    p["alpha"]=round(min(1,max(.5,p["alpha"]+r.choice([-1,1])*r.uniform(.04,.1)*m)),3);return "ink_shade",f"rgb{p['ink']} a={p['alpha']}"
def m_dash(p,r,m):
    p["dash"]="–";return "dash_variant","hyphen->en dash"
ALL=[m_size,m_spacing,m_font,m_accent,m_base,m_rot,m_off,m_ink,m_dash]
DIFF={"subtle":(0.5,[1],[m_size,m_spacing,m_base,m_rot,m_off,m_ink]),
      "medium":(1.0,[1,2],ALL),"obvious":(2.0,[2,3,4],ALL)}

def augment(img,r):
    ang=r.uniform(-.6,.6);img=img.rotate(ang,resample=Image.BICUBIC,fillcolor=(255,255,255))
    blur=r.uniform(.3,1.0);img=img.filter(ImageFilter.GaussianBlur(blur))
    a=np.asarray(img).astype(np.float32);tint=r.uniform(0,10);a[...,2]-=tint;a[...,1]-=tint*.4
    a=(a-128)*r.uniform(.9,1.1)+128+r.uniform(-12,8);sig=r.uniform(2,6);a+=np.random.default_rng(r.randrange(1<<30)).normal(0,sig,a.shape)
    q=r.randint(55,90);return Image.fromarray(np.clip(a,0,255).astype(np.uint8)),dict(aug_rot=round(ang,2),aug_blur=round(blur,2),aug_noise=round(sig,2),jpeg_q=q)

def render(p,dpi,r,out_img,out_crop,tmp):
    pdf=os.path.join(tmp,"t.pdf");cy_pt=build_page(pdf,p)
    subprocess.run(["pdftoppm","-r",str(dpi),"-png","-singlefile",pdf,os.path.join(tmp,"t")],check=True)
    img=Image.open(os.path.join(tmp,"t.png")).convert("RGB");img,aug=augment(img,r)
    img.save(out_img,quality=aug["jpeg_q"])
    k=dpi/72;cx=(A4[0]-62-100)*k;cy=(cy_pt+10)*k;hw,hh=190*k/1.2*.9,105*k/1.2*.9
    img.crop((int(cx-hw),int(cy-hh),int(cx+hw),int(cy+hh))).save(out_crop,quality=aug["jpeg_q"]);return aug

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--n",type=int,default=100);ap.add_argument("--out",default="dataset")
    ap.add_argument("--seed",type=int,default=42);ap.add_argument("--dpi",type=int,default=120);a=ap.parse_args()
    r=random.Random(a.seed);os.makedirs(a.out+"/pages",exist_ok=True);os.makedirs(a.out+"/stamp_crops",exist_ok=True)
    rows=[];tmp=tempfile.mkdtemp()
    jobs=[("reference","none")]*a.n+[("counterfeit",d) for d in ["subtle","medium","obvious"]*(a.n//3)]
    jobs+= [("counterfeit",r.choice(list(DIFF))) for _ in range(a.n-len([j for j in jobs if j[0]=="counterfeit"]))]
    r.shuffle(jobs)
    for i,(label,diff) in enumerate(jobs):
        p=copy.deepcopy(REF);muts=[]
        if label=="counterfeit":
            m,ks,pool=DIFF[diff];k=r.choice(ks);chosen=[];
            for f in r.sample(pool,min(k,len(pool))):
                muts.append(f(p,r,m))
        sid=f"{i:04d}_{label}";aug=render(p,a.dpi,r,f"{a.out}/pages/{sid}.jpg",f"{a.out}/stamp_crops/{sid}.jpg",tmp)
        rows.append(dict(id=sid,image=f"pages/{sid}.jpg",crop=f"stamp_crops/{sid}.jpg",label=label,difficulty=diff,
            mutations=json.dumps([f"{n}:{d}" for n,d in muts],ensure_ascii=False),split="val" if r.random()<.2 else "train",**aug,stamp_params=json.dumps(p,ensure_ascii=False)))
    with open(a.out+"/labels.csv","w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(len(rows),"samples ->",a.out)
if __name__=="__main__": main()

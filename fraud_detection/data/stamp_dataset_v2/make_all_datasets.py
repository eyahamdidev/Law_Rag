#!/usr/bin/env python3
"""Synthetic stamp datasets for 4 specimen documents (all issuers fictitious, stamps read SPECIMEN / FAUX or FICTIF).
Each document: reference (fixed stamp) vs counterfeit (reference + 1-4 randomized mutations, 3 difficulty levels).
Scan augmentation identical for both classes.
  python make_all_datasets.py --n 50 --out dataset_all --seed 42 --dpi 120
"""
import argparse, copy, csv, json, math, os, random, subprocess, tempfile, shutil
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
import pdfplumber
import make_dataset as md          # fonts, augment(), balance-sheet document
from make_dataset import *         # noqa
HERE=os.path.dirname(os.path.abspath(__file__))
FLAG=os.path.join(HERE,"assets","tn.svg")
LABEL_PDF=os.path.join(HERE,"assets","Attestation_de_Labellisation_Startup.pdf")
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF

# ---------------- shared stamp text helper ----------------
def put_line(c,s,f,z,cs,yy):
    wd=stringWidth(s,f,z)+cs*len(s)
    o=c.beginText();o.setFont(f,z);o.setCharSpace(cs);o.setTextOrigin(-wd/2,yy);o.textOut(s);c.drawText(o)
def drop(s,on): 
    return s if on else s.replace("É","E").replace("È","E")

# ---------------- OVAL stamp (capital release) ----------------
CAP_REF=dict(fonts=["Ser-B","Ser-B","Ser","Ser-B","Ser-B","Ser"],sizes=[8,8,8,9.5,8.5,7],cs=[0,0,0,0,0,0],
    base=[0,0,18,5,-8,-20],rot=5.0,dx=0.0,dy=0.0,ink=[0.10,0.22,0.68],alpha=0.82,
    accents=[True]*6,dash="-",geo=dict(outer=[96,62],mid=[90,56],inner=[68,36],lw=[2.2,.8,1.0]))
CAP_ACC=[3,4]
def cap_lines(p):
    a=p["accents"]
    return ["BANQUE PUBLIQUE FICTIVE","TUNIS %s TUNISIE"%p["dash"],"I.F. : 1745039 C/P/000",drop("23 FÉV 2024",a[3]),drop("SPÉCIMEN / FAUX",a[4]),"NE PAS UTILISER"]
def arc_text(c,s,font,size,a,b,center,top,spc):
    ws=[stringWidth(ch,font,size)+spc for ch in s]
    spd=lambda t: math.hypot(a*math.sin(t),b*math.cos(t))
    tc=math.radians(center);total=sum(ws)/spd(tc);sgn=-1 if top else 1;t=tc-sgn*total/2
    for ch,wd in zip(s,ws):
        dt=sgn*wd/spd(t);tm=t+dt/2;x,yv=a*math.cos(tm),b*math.sin(tm)
        na=math.degrees(math.atan2(math.sin(tm)/b,math.cos(tm)/a));rot=na-90 if top else na+90
        c.saveState();c.translate(x,yv);c.rotate(rot);c.setFont(font,size);c.drawCentredString(0,0,ch);c.restoreState();t+=dt
def draw_capital_stamp(c,p,cx,cy):
    g=p["geo"];c.saveState();c.translate(cx+p["dx"],cy+p["dy"]);c.rotate(p["rot"])
    ink=Color(*p["ink"],alpha=p["alpha"]);c.setStrokeColor(ink);c.setFillColor(ink)
    for (a,b),lw in zip([g["outer"],g["mid"],g["inner"]],g["lw"]): c.setLineWidth(lw);c.ellipse(-a,-b,a,b)
    L=cap_lines(p);F,Z,CS,B=p["fonts"],p["sizes"],p["cs"],p["base"]
    arc_text(c,L[0],F[0],Z[0],73+B[0],41+B[0],90,True,0.8+CS[0])
    arc_text(c,L[1],F[1],Z[1],84+B[1],51+B[1],270,False,0.8+CS[1])
    for i in range(2,6): put_line(c,L[i],F[i],Z[i],CS[i],B[i])
    c.restoreState()
def cap_geo(p,r,m):
    g=p["geo"];k=r.choice([-1,1])*r.uniform(.03,.08)*m;sx=1+k;sy=1+k*r.choice([-1,1,.4])
    for key in ("outer","mid"): g[key]=[round(g[key][0]*sx,2),round(g[key][1]*sy,2)]
    g["lw"][0]=round(max(.8,g["lw"][0]+r.choice([-1,1])*r.uniform(.2,.5)*m),2)
    return "geometry",f"oval scale x{sx:.3f} y{sy:.3f}, outer lw {g['lw'][0]}"

# ---------------- RECTANGLE stamp (grant decision) ----------------
SUB_REF=dict(fonts=["Ser-B","Ser","Ser","Ser","Ser-B","Ser-B"],sizes=[9,8.5,8.5,8.5,10,7.5],cs=[0]*6,
    base=[31,17,3,-11,-25,-39],rot=-4.0,dx=0.0,dy=0.0,ink=[0.38,0.20,0.62],alpha=0.82,accents=[True]*6,dash="-",
    geo=dict(sw=190,sh=96,lw=[2.2,.8],inset=4))
SUB_ACC=[0,1,5]
def sub_lines(p):
    a=p["accents"];d=p["dash"]
    return [drop("COMITÉ FICTIF D'ATTRIBUTION",a[0]),drop("FONDS RÉGIONAL %s EXEMPLE"%d,a[1]),"I.F. : 1928374 A/M/000","Sfax %s Tunisie"%d,"12 MAR 2024",drop("SPÉCIMEN / FAUX %s NE PAS UTILISER"%d,a[5])]
def draw_subvention_stamp(c,p,cx,cy):
    g=p["geo"];c.saveState();c.translate(cx+p["dx"],cy+p["dy"]);c.rotate(p["rot"])
    ink=Color(*p["ink"],alpha=p["alpha"]);c.setStrokeColor(ink);c.setFillColor(ink)
    sw,sh=g["sw"],g["sh"];c.setLineWidth(g["lw"][0]);c.rect(-sw/2,-sh/2,sw,sh,fill=0)
    i=g["inset"];c.setLineWidth(g["lw"][1]);c.rect(-sw/2+i,-sh/2+i,sw-2*i,sh-2*i,fill=0)
    for k,s in enumerate(sub_lines(p)): put_line(c,s,p["fonts"][k],p["sizes"][k],p["cs"][k],p["base"][k])
    c.restoreState()
def sub_geo(p,r,m):
    g=p["geo"];dw=r.choice([-1,1])*r.uniform(2,6)*m;dh=r.choice([-1,1])*r.uniform(1,4)*m
    g["sw"]=round(g["sw"]+dw,2);g["sh"]=round(g["sh"]+dh,2)
    g["lw"][0]=round(max(.8,g["lw"][0]+r.choice([-1,1])*r.uniform(.2,.5)*m),2);g["inset"]=round(max(2,g["inset"]+r.choice([-1,1])*r.uniform(.5,1.2)*m),2)
    return "geometry",f"rect {dw:+.1f}x{dh:+.1f}pt, outer lw {g['lw'][0]}, inset {g['inset']}"

# ---------------- generic mutators for vector stamps ----------------
def make_mutators(REF,ACC,geo):
    n=len(REF["sizes"])
    def size(p,r,m): i=r.randrange(n);d=r.choice([-1,1])*r.uniform(.3,.8)*m;p["sizes"][i]=round(p["sizes"][i]+d,2);return "size",f"line{i+1} {d:+.2f}pt"
    def spacing(p,r,m): i=r.randrange(n);d=r.uniform(.15,.4)*m;p["cs"][i]=round(d,3);return "letter_spacing",f"line{i+1} +{d:.2f}pt"
    def font(p,r,m): i=r.randrange(n);alt=r.choice(ALT_FONTS[REF["fonts"][i]]);p["fonts"][i]=alt;return "font_substitution",f"line{i+1} {REF['fonts'][i]}->{alt}"
    def accent(p,r,m): i=r.choice(ACC);p["accents"][i]=False;return "dropped_accents",f"line{i+1}"
    def base(p,r,m): i=r.randrange(n);d=r.choice([-1,1])*r.uniform(.8,2.2)*m;p["base"][i]=round(p["base"][i]+d,2);return "baseline_shift",f"line{i+1} {d:+.2f}pt"
    def rot(p,r,m): d=r.choice([-1,1])*r.uniform(.7,2.0)*m;p["rot"]=round(p["rot"]+d,2);return "rotation",f"{d:+.2f}deg"
    def off(p,r,m):
        dx,dy=[r.choice([-1,1])*r.uniform(1,4)*m for _ in range(2)];p["dx"],p["dy"]=round(dx,2),round(dy,2);return "offset",f"dx{dx:+.2f} dy{dy:+.2f}pt"
    def ink(p,r,m):
        p["ink"]=[round(min(1,max(0,v+r.choice([-1,1])*r.uniform(.02,.06)*m)),3) for v in p["ink"]]
        p["alpha"]=round(min(1,max(.5,p["alpha"]+r.choice([-1,1])*r.uniform(.04,.1)*m)),3);return "ink_shade",f"rgb{p['ink']} a={p['alpha']}"
    def dash(p,r,m): p["dash"]="–";return "dash_variant","hyphen->en dash"
    allm=[size,spacing,font,accent,base,rot,off,ink,dash,geo]
    return {"subtle":(0.5,[1],[size,spacing,base,rot,off,ink,geo]),"medium":(1.0,[1,2],allm),"obvious":(2.0,[2,3,4],allm)}

# ---------------- RASTER stamp (labellisation, hand-made stamp image) ----------------
def load_label_stamp(tmp):
    pg=pdfplumber.open(LABEL_PDF).pages[0];im=pg.images[0];bbox=(im["x0"],im["top"],im["x1"],im["bottom"])
    subprocess.run(["pdfimages","-png",LABEL_PDF,os.path.join(tmp,"lab")],check=True)
    a=Image.open(os.path.join(tmp,"lab-000.png")).convert("RGB");a.putalpha(Image.open(os.path.join(tmp,"lab-001.png")).convert("L"));return a,bbox
LAB_REF=dict(scale=1.0,rot=0.0,dx=0.0,dy=0.0,alpha=1.0,rgb_shift=[0,0,0],res=1.0,jpeg=100,flatten=0.0,clip=0.0)
def lm_scale(p,r,m): d=r.choice([-1,1])*r.uniform(.015,.05)*m;p["scale"]=round(1+d,4);return "scale",f"{d*100:+.1f}%"
def lm_rot(p,r,m): d=r.choice([-1,1])*r.uniform(.5,2)*m;p["rot"]=round(d,2);return "rotation",f"{d:+.2f}deg"
def lm_off(p,r,m): dx,dy=[r.choice([-1,1])*r.uniform(1,4)*m for _ in range(2)];p["dx"],p["dy"]=round(dx,2),round(dy,2);return "offset",f"dx{dx:+.2f} dy{dy:+.2f}pt"
def lm_color(p,r,m): p["rgb_shift"]=[int(r.choice([-1,1])*r.uniform(8,25)*m) for _ in range(3)];return "ink_color_shift",f"{p['rgb_shift']}"
def lm_alpha(p,r,m): p["alpha"]=round(1-r.uniform(.05,.2)*m,3);return "opacity",f"{p['alpha']}"
def lm_res(p,r,m): p["res"]=round(max(.25,1-r.uniform(.15,.35)*m),3);return "resolution_mismatch",f"downscale to {p['res']}"
def lm_jpeg(p,r,m): p["jpeg"]=int(max(12,90-25*m*r.uniform(.8,1.4)));return "jpeg_blockiness",f"q={p['jpeg']}"
def lm_flat(p,r,m): p["flatten"]=round(min(1,r.uniform(.3,.6)*m),2);return "ink_flattening",f"strength {p['flatten']}"
def lm_clip(p,r,m): p["clip"]=round(r.uniform(.02,.05)*m,3);return "edge_clipping",f"{p['clip']*100:.1f}% of one edge"
LALL=[lm_scale,lm_rot,lm_off,lm_color,lm_alpha,lm_res,lm_jpeg,lm_flat,lm_clip]
LDIFF={"subtle":(0.5,[1],[lm_scale,lm_rot,lm_off,lm_color,lm_alpha]),"medium":(1.0,[1,2],LALL),"obvious":(2.0,[2,3,4],LALL)}
def transform_stamp(st,p,r):
    s=st.copy()
    if p["res"]<1: w,h=s.size;s=s.resize((int(w*p["res"]),int(h*p["res"])),Image.BILINEAR).resize((w,h),Image.BILINEAR)
    if p["jpeg"]<100:
        import io;rgb=s.convert("RGB");b=io.BytesIO();rgb.save(b,"JPEG",quality=p["jpeg"]);b.seek(0);al=s.split()[3];s=Image.open(b).convert("RGB");s.putalpha(al)
    a=np.asarray(s).astype(np.float32)
    if p["flatten"]>0:
        mean=a[a[...,3]>40][:,:3].mean(0);k=p["flatten"];a[...,:3]=a[...,:3]*(1-k)+mean*k
    a[...,:3]+=np.array(p["rgb_shift"],np.float32);a[...,3]*=p["alpha"]
    if p["clip"]>0:
        h,w=a.shape[:2];e=int(max(w,h)*p["clip"]);ed=int(p["clip"]*1000)%4
        if ed==0:a[:, :e,3]=0
        elif ed==1:a[:, -e:,3]=0
        elif ed==2:a[:e,:,3]=0
        else:a[-e:,:,3]=0
    s=Image.fromarray(np.clip(a,0,255).astype(np.uint8),"RGBA")
    return s

def render_label(p,dpi,r,out_img,out_crop,tmp,cache={}):
    if "st" not in cache: cache["st"],cache["bbox"]=load_label_stamp(tmp)
    st,bbox=cache["st"],cache["bbox"];k=dpi/72
    subprocess.run(["pdftoppm","-r",str(dpi),"-png","-singlefile",LABEL_PDF,os.path.join(tmp,"lab_page")],check=True)
    page=Image.open(os.path.join(tmp,"lab_page.png")).convert("RGBA")
    x0,y0,x1,y1=[int(v*k) for v in bbox];pad=2
    page.paste((255,255,255,255),(x0-pad,y0-pad,x1+pad,y1+pad))
    s=transform_stamp(st,p,r);bw,bh=(x1-x0),(y1-y0);sc=p["scale"]
    s=s.resize((int(bw*sc),int(bh*sc)),Image.LANCZOS)
    if p["rot"]: s=s.rotate(p["rot"],resample=Image.BICUBIC,expand=True)
    cx=(x0+x1)/2+p["dx"]*k;cy=(y0+y1)/2+p["dy"]*k
    layer=Image.new("RGBA",page.size,(0,0,0,0));layer.paste(s,(int(cx-s.width/2),int(cy-s.height/2)))
    page=Image.alpha_composite(page,layer).convert("RGB");img,aug=md.augment(page,r)
    img.save(out_img,quality=aug["jpeg_q"]);hw,hh=bw*.62,bh*.62
    img.crop((int((x0+x1)/2-hw),int((y0+y1)/2-hh),int((x0+x1)/2+hw),int((y0+y1)/2+hh))).save(out_crop,quality=aug["jpeg_q"]);return aug

# ---------------- generic vector render ----------------
def render_vec(builder,crop_half,p,dpi,r,out_img,out_crop,tmp):
    pdf=os.path.join(tmp,"t.pdf");cx_pt,cy_pt=builder(pdf,p)
    subprocess.run(["pdftoppm","-r",str(dpi),"-png","-singlefile",pdf,os.path.join(tmp,"t")],check=True)
    img,aug=md.augment(Image.open(os.path.join(tmp,"t.png")).convert("RGB"),r);img.save(out_img,quality=aug["jpeg_q"])
    k=dpi/72;hw,hh=crop_half[0]*k,crop_half[1]*k;cx,cy=cx_pt*k,(cy_pt+crop_half[2])*k
    img.crop((int(cx-hw),int(cy-hh),int(cx+hw),int(cy+hh))).save(out_crop,quality=aug["jpeg_q"]);return aug

def render_balance(p,dpi,r,oi,oc,tmp): return md.render(p,dpi,r,oi,oc,tmp)

DOCS={
 "balance":dict(ref=md.REF,diff=md.DIFF,render=render_balance,title="Attestation de solde bancaire (BMC, text-only blue stamp)"),
 "capital":dict(ref=CAP_REF,diff=None,render=lambda p,d,r,oi,oc,t: render_vec(build_capital,(115,80,0),p,d,r,oi,oc,t),title="Attestation de libération du capital (BPAE, oval blue stamp)"),
 "subvention":dict(ref=SUB_REF,diff=None,render=lambda p,d,r,oi,oc,t: render_vec(build_subvention,(115,70,0),p,d,r,oi,oc,t),title="Décision d'attribution de subvention (FRAI, rectangular violet stamp)"),
 "labellisation":dict(ref=LAB_REF,diff=LDIFF,render=render_label,title="Attestation de labellisation Startup Act (round raster stamp)"),
}
DOCS["capital"]["diff"]=make_mutators(CAP_REF,CAP_ACC,cap_geo)
DOCS["subvention"]["diff"]=make_mutators(SUB_REF,SUB_ACC,sub_geo)

def build_capital(path,sp):
    W,H=A4;L,R=62,W-62
    c=canvas.Canvas(path,pagesize=A4);c.setTitle("Attestation de libération du capital social - SPECIMEN")
    def T(x,y,s,f="Ser",sz=9,col=black,al="l"):
        c.setFont(f,sz);c.setFillColor(col)
        {"l":c.drawString,"r":c.drawRightString,"c":c.drawCentredString}[al](x,H-y,s)
    def flag(x,y,w=63):
        d=svg2rlg(FLAG); k=w/d.width
        d.scale(k,k); d.width*=k; d.height*=k
        renderPDF.draw(d,c,x,y)
    # header
    T(L,70,"RÉPUBLIQUE TUNISIENNE","Ser-B",10)
    T(L,84,"Banque Publique d'Appui aux Entreprises (BPAE)")
    T(L,97,"Direction Entreprises & Startups")
    T(L,110,"Agence Les Berges du Lac","Ser",8)
    flag(W/2-31.5,H-114,63)
    c.setFillColor(black)
    c.setFont("Ar-B",9.5);c.drawRightString(R,H-70,ar("الجمهورية التونسية"))
    c.setFont("Ar",8);c.drawRightString(R,H-84,ar("البنك الوطني لدعم المؤسسات"))
    c.drawRightString(R,H-97,ar("إدارة المؤسسات والمؤسسات الناشئة"))
    c.setFont("Ar",7);c.drawRightString(R,H-110,ar("وكالة ضفاف البحيرة"))
    T(L,145,"N/Réf : ","Ser-B",9);T(L+34,145,"BPAE/2024/ATT-05216")
    T(W/2-20,145,"Agence : ","Ser-B",9);T(W/2+20,145,"Lac 2 (0412)")
    T(R,145,"Tunis, le : Dimanche 25 Février 2024","Ser",9,black,"r")
    T(W/2,185,"ATTESTATION DE LIBÉRATION DU CAPITAL SOCIAL","Ser-B",14.5,black,"c")
    c.setLineWidth(1);c.line(W/2-190,H-189,W/2+190,H-189)
    T(W/2,202,"« CRÉATION D'ENTREPRISE - STARTUP »","Ser-B",9,black,"c")
    body=ParagraphStyle("b",fontName="Ser",fontSize=9.5,leading=17,alignment=TA_JUSTIFY,firstLineIndent=22)
    txt=("La Banque Publique d'Appui aux Entreprises, agence Les Berges du Lac, vu le Code des Sociétés Commerciales promulgué par la Loi n° 2000-93 "
    "du 3 novembre 2000, vu la Loi n° 2018-20 du 17 avril 2018 relative aux Startups, vu le certificat de dépôt des fonds n° CD-2024-11873 et sur "
    "présentation des statuts de la société, atteste par la présente que le capital social de la société ci-après désignée a été "
    "<b>LIBÉRÉ</b> dans les conditions suivantes :")
    p=Paragraph(txt,body);w,h=p.wrap(R-L,300);p.drawOn(c,L,H-218-h)
    rows=[["Dénomination Sociale","ATLAS AGRITECH"],
    ["Forme Juridique","Société à Responsabilité Limitée (S.A.R.L)"],
    ["Identifiant Unique / RNE","1745093 C/P/000 (Registre National des Entreprises : 91203/118/52)"],
    ["Siège Social","Pôle Technologique d'El Ghazala, 2083 Ariana, Tunisie"],
    ["Capital Social Souscrit","50 000,00 DT (cinquante mille dinars tunisiens)"],
    ["Capital Libéré","30 000,00 DT (trente-cinq mille dinars tunisiens)"],
    ["Date du Dépôt des Fonds","28 Février 2024"],
    ["Compte Bloqué (RIB)","08 006 0187452963104 61"]]
    st=ParagraphStyle("c",fontName="Ser",fontSize=9.5,leading=12)
    sb=ParagraphStyle("cb",parent=st,fontName="Ser-B")
    data=[[Paragraph(a,sb),Paragraph(b,st)] for a,b in rows]
    t=Table(data,colWidths=[130,R-L-130]);t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,black),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),("LEFTPADDING",(0,0),(-1,-1),8)]))
    tw,th=t.wrap(R-L,400);ty=H-218-h-16-th;t.drawOn(c,L,ty)
    y=H-ty+20
    T(L,y,"Mentions :","Ser-B",9)
    small=ParagraphStyle("s",fontName="Ser",fontSize=9,leading=13,alignment=TA_JUSTIFY)
    for s in ["• La présente attestation est délivrée pour servir et valoir ce que de droit, notamment pour l'immatriculation au Registre National des Entreprises et la demande du label Startup.",
     "• Les fonds demeurent bloqués jusqu'à la constitution définitive de la société et la remise de l'extrait du RNE à l'agence."]:
        p=Paragraph(s,small);pw,ph=p.wrap(R-L,100);y+=6;p.drawOn(c,L,H-y-ph);y+=ph
    y+=30
    T(L,y,"Le Directeur de l'Agence,","Ser",9.5)
    T(R-170,y,"Pour la Banque et par délégation,","Ser-B",9.5)
    T(L+8,y+26,"Mme Gharbi","Ser-I",13)

    ret=(R-95,y+62)
    draw_capital_stamp(c,sp,R-95,H-(y+62))
    c.setStrokeColor(black);c.setLineWidth(.8);c.line(L,58,R,58)
    T(L,H-45,"Banque Publique d'Appui aux Entreprises - République Tunisienne","Ser",8,HexColor("#444444"))
    T(R,H-45,"Document d'Attestation - Page 1 / 3","Ser",8,HexColor("#444444"),"r")

    c.save()
    return ret


def build_subvention(path,sp):
    W,H=A4;L,R=62,W-62
    c=canvas.Canvas(path,pagesize=A4);c.setTitle("Décision d'attribution de subvention - SPECIMEN")
    def T(x,y,s,f="Ser",sz=9,col=black,al="l"):
        c.setFont(f,sz);c.setFillColor(col)
        {"l":c.drawString,"r":c.drawRightString,"c":c.drawCentredString}[al](x,H-y,s)
    def flag(x,y,w=63):
        d=svg2rlg(FLAG); k=w/d.width
        d.scale(k,k); d.width*=k; d.height*=k
        renderPDF.draw(d,c,x,y)
    # header
    T(L,70,"RÉPUBLIQUE TUNISIENNE","Ser-B",10)
    T(L,84,"Fonds Régional d'Appui à l'Innovation (FRAI)")
    T(L,97,"Commission d'Attribution des Subventions")
    T(L,110,"Direction des Programmes Startups","Ser",8)
    flag(W/2-31.5,H-114,63)
    c.setFillColor(black)
    c.setFont("Ar-B",9.5);c.drawRightString(R,H-70,ar("الجمهورية التونسية"))
    c.setFont("Ar",8);c.drawRightString(R,H-84,ar("صندوق دعم الابتكار الجهوي"))
    c.drawRightString(R,H-97,ar("لجنة إسناد المنح"))
    c.setFont("Ar",7);c.drawRightString(R,H-110,ar("إدارة برامج المؤسسات الناشئة"))
    T(L,145,"N/Réf : ","Ser-B",9);T(L+34,145,"FRAI/2024/SUB-0731")
    T(W/2-20,145,"Session : ","Ser-B",9);T(W/2+22,145,"Mars 2024")
    T(R,145,"Tunis, le : 09 Mars 2024","Ser",9,black,"r")
    T(W/2,185,"DÉCISION D'ATTRIBUTION DE SUBVENTION","Ser-B",15,black,"c")
    c.setLineWidth(1);c.line(W/2-152,H-189,W/2+152,H-189)
    T(W/2,202,"« PROGRAMME INNOVATION RÉGIONALE »","Ser-B",9,black,"c")
    body=ParagraphStyle("b",fontName="Ser",fontSize=9.5,leading=17,alignment=TA_JUSTIFY,firstLineIndent=22)
    txt=("Le Directeur Général du Fonds Régional d'Appui à l'Innovation, vu la Loi n° 2018-20 du 17 avril 2018 relative aux Startups, "
    "vu le Décret n° 2019-412 du 31 février 2019 fixant les modalités d'octroi des subventions à l'innovation, et sur avis favorable de la "
    "Commission d'Attribution émis lors de sa délibération en date du 14 Mars 2024, atteste par la présente que le bénéficiaire "
    "ci-après désigné se voit accorder une <b>SUBVENTION D'APPUI À L'INNOVATION</b> :")
    p=Paragraph(txt,body);w,h=p.wrap(R-L,300);p.drawOn(c,L,H-218-h)
    rows=[["Bénéficiaire","SOCIÉTÉ NORD-AFRICAINE DE DONNÉES APPLIQUÉES (SNDA)"],
    ["Forme Juridique","Société par Actions Simplifiée (S.A.S)"],
    ["Identifiant Unique / RNE","1928374 B/P/000 (Registre National des Entreprises : 83921/044/17)"],
    ["Siège Social","Technopôle de Sfax, Route de Tunis Km 9, 3052 Sfax, Tunisie"],
    ["Montant Accordé","45 000 DT (quarante mille dinars tunisiens)"],
    ["Période d'Exécution","Vingt-quatre (24) mois du 09 Mars 2024 au 08 Septembre 2025"]]
    st=ParagraphStyle("c",fontName="Ser",fontSize=9.5,leading=12)
    sb=ParagraphStyle("cb",parent=st,fontName="Ser-B")
    data=[[Paragraph(a,sb),Paragraph(b,st)] for a,b in rows]
    t=Table(data,colWidths=[130,R-L-130]);t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,black),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),("LEFTPADDING",(0,0),(-1,-1),8)]))
    tw,th=t.wrap(R-L,400);ty=H-218-h-18-th;t.drawOn(c,L,ty)
    y=H-ty+22
    T(L,y,"Droits et Obligations :","Ser-B",9)
    small=ParagraphStyle("s",fontName="Ser",fontSize=9,leading=14,alignment=TA_JUSTIFY)
    for s in ["• Le versement de la subvention s'effectue en deux tranches, la seconde étant conditionnée à la remise d'un rapport d'avancement technique.",
     "• Le bénéficiaire s'engage à justifier l'utilisation des fonds et à déposer annuellement ses états financiers auprès du Secrétariat de la Commission."]:
        p=Paragraph(s,small);pw,ph=p.wrap(R-L,100);y+=8;p.drawOn(c,L,H-y-ph);y+=ph
    y+=36
    T(L,y,"Le Directeur Général du FRAI,","Ser",9.5)
    T(R-170,y,"Pour la Commission et par délégation,","Ser-B",9.5)
    T(L+8,y+26,"M. Trabelsi","Ser-I",13)

    ret=(R-120,y+95)
    draw_subvention_stamp(c,sp,R-120,H-(y+95))
    c.setStrokeColor(black);c.setLineWidth(.8);c.line(L,58,R,58)
    T(L,H-45,"Fonds Régional d'Appui à l'Innovation - République Tunisienne","Ser",8,HexColor("#444444"))
    T(R,H-45,"Document de Décision - Page 1 / 2","Ser",8,HexColor("#444444"),"r")

    c.save()
    return ret

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--n",type=int,default=50,help="samples per class per document")
    ap.add_argument("--out",default="dataset_all");ap.add_argument("--seed",type=int,default=42);ap.add_argument("--dpi",type=int,default=120)
    ap.add_argument("--docs",default="balance,capital,subvention,labellisation");a=ap.parse_args()
    allrows=[];tmp=tempfile.mkdtemp()
    for di,doc in enumerate(a.docs.split(",")):
        D=DOCS[doc];REFP=D["ref"];r=random.Random(a.seed*100+di);os.makedirs(f"{a.out}/{doc}/pages",exist_ok=True);os.makedirs(f"{a.out}/{doc}/stamp_crops",exist_ok=True)
        lv=list(D["diff"]);jobs=[("reference","none")]*a.n+[("counterfeit",lv[i%3]) for i in range(a.n)];r.shuffle(jobs);rows=[]
        for i,(label,diff) in enumerate(jobs):
            p=copy.deepcopy(REFP);muts=[]
            if label=="counterfeit":
                m,ks,pool=D["diff"][diff];k=r.choice(ks)
                for f in r.sample(pool,min(k,len(pool))): muts.append(f(p,r,m))
            sid=f"{doc}_{i:04d}_{label}";aug=D["render"](p,a.dpi,r,f"{a.out}/{doc}/pages/{sid}.jpg",f"{a.out}/{doc}/stamp_crops/{sid}.jpg",tmp)
            rows.append(dict(doc=doc,id=sid,image=f"{doc}/pages/{sid}.jpg",crop=f"{doc}/stamp_crops/{sid}.jpg",label=label,difficulty=diff,
                mutations=json.dumps([f"{n}:{d}" for n,d in muts],ensure_ascii=False),split="val" if r.random()<.2 else "train",**aug,stamp_params=json.dumps(p,ensure_ascii=False)))
        with open(f"{a.out}/{doc}/labels.csv","w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        allrows+=rows;print(doc,len(rows))
    with open(f"{a.out}/labels_all.csv","w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(allrows[0]));w.writeheader();w.writerows(allrows)
    print("total",len(allrows))
if __name__=="__main__": main()

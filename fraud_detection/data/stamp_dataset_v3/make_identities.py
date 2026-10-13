#!/usr/bin/env python3
"""Identity-level stamp dataset: 26 new fictitious stamp identities (oval, circle, rect, text-only) + the 4 originals (from v2).
Per identity: 1 clean genuine, 10 harmless degraded genuine, N counterfeit (random 1-4 mutations, 3 difficulty levels).
Same degradation distribution is applied to harmless and counterfeit rows. Split is BY IDENTITY (18 train / 6 val / 6 test, stratified by family).
  python make_identities.py --out dataset --counterfeit 40 --harmless 10 --seed 42 [--v2 ../stamp_dataset_v2/dataset_all]
All issuers fictitious; every stamp carries SPÉCIMEN / FAUX."""
import argparse, copy, csv, io, json, math, os, random, shutil, subprocess, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import make_dataset as md            # registers fonts, helpers
from make_dataset import *           # noqa
ACC_MAP=str.maketrans("ÉÈÊÀÂÇÔÎÛ","EEEAACOIU")
ALT={"Ser-B":["DVS-B","LSans-B","Ser-BI"],"Ser":["DVS","LSans","Ser-I"],"LSans-B":["Ser-B","DVS-B"],"LSans":["Ser","DVS"],"DVS-B":["Ser-B","LSans-B"],"DVS":["Ser","LSans"]}
FAMS={"oval":7,"circle":7,"rect":7,"text":5}
PREF=["AGENCE FICTIVE","COMITÉ FICTIF","FONDS EXEMPLE","OFFICE FICTIF","CENTRE EXEMPLE","SERVICE FICTIF","DIRECTION EXEMPLE"]
SHORT=["INNOVATION","FORMATION","EXPORT","AGRICULTURE","ÉNERGIE","RECHERCHE","COMMERCE","ARTISANAT","TOURISME","TRANSPORTS","INDUSTRIE","ENVIRONNEMENT","SANTÉ","HABITAT","NUMÉRIQUE","PÊCHE"]
CITY=["Tunis","Sfax","Sousse","Nabeul","Bizerte","Gabès","Kairouan","Monastir","Gafsa","Ariana","Medenine","Tozeur"]
MON=["JANV","FÉVR","MARS","AVR","MAI","JUIN","JUIL","AOÛT","SEPT","OCT","NOV","DÉC"]
COLORS=[(0.10,0.22,0.68),(0.38,0.20,0.62),(0.08,0.08,0.10),(0.72,0.10,0.18),(0.08,0.45,0.25),(0.05,0.12,0.40),(0.30,0.12,0.45),(0.55,0.10,0.10)]
FONTSETS=[("Ser-B","Ser"),("LSans-B","LSans"),("DVS-B","DVS")]
def tx(t,i,p):
    if not p["accents"][i]: t=t.translate(ACC_MAP)
    if p["dash"]!="-": t=t.replace(" - "," %s "%p["dash"])
    return t
def fit(s,f,z,a,b,maxdeg=150,spc=0.8):
    spd=math.hypot(a*math.sin(math.pi/2),b*math.cos(math.pi/2))
    while z>5.2 and math.degrees(sum(stringWidth(ch,f,z)+spc for ch in s)/spd)>maxdeg: z*=0.95
    return round(z,2)
def arc_text(c,s,font,size,a,b,center,top,spc):
    ws=[stringWidth(ch,font,size)+spc for ch in s];spd=lambda t: math.hypot(a*math.sin(t),b*math.cos(t))
    tc=math.radians(center);total=sum(ws)/spd(tc);sgn=-1 if top else 1;t=tc-sgn*total/2
    for ch,wd in zip(s,ws):
        dt=sgn*wd/spd(t);tm=t+dt/2;x,yv=a*math.cos(tm),b*math.sin(tm)
        na=math.degrees(math.atan2(math.sin(tm)/b,math.cos(tm)/a));rot=na-90 if top else na+90
        c.saveState();c.translate(x,yv);c.rotate(rot);c.setFont(font,size);c.drawCentredString(0,0,ch);c.restoreState();t+=dt
def put_line(c,s,f,z,cs,yy):
    wd=stringWidth(s,f,z)+cs*len(s);o=c.beginText();o.setFont(f,z);o.setCharSpace(cs);o.setTextOrigin(-wd/2,yy);o.textOut(s);c.drawText(o)
def draw_stamp(c,p,cx,cy):
    c.saveState();c.translate(cx+p["dx"],cy+p["dy"]);c.rotate(p["rot"])
    ink=Color(*p["ink"],alpha=p["alpha"]);c.setStrokeColor(ink);c.setFillColor(ink);g=p["geo"];sh=p["shape"]
    if sh in("oval","circle"):
        for (a,b),lw in zip([g["outer"],g["mid"],g["inner"]],g["lw"]): c.setLineWidth(lw);c.ellipse(-a,-b,a,b)
        ia,ib=g["inner"];ma,mb=g["mid"]
    elif sh=="rect":
        sw,sh_=g["sw"],g["sh"];c.setLineWidth(g["lw"][0]);c.rect(-sw/2,-sh_/2,sw,sh_,fill=0)
        if g["lw"][1]>0: i=g["inset"];c.setLineWidth(g["lw"][1]);c.rect(-sw/2+i,-sh_/2+i,sw-2*i,sh_-2*i,fill=0)
    for i,(t,role) in enumerate(zip(p["texts"],p["roles"])):
        f,z,cs,b=p["fonts"][i],p["sizes"][i],p["cs"][i],p["base"][i]
        if role=="arc_top": arc_text(c,tx(t,i,p),f,z,ia+4.5+b,ib+4.5+b,90,True,0.8+cs)
        elif role=="arc_bot": arc_text(c,tx(t,i,p),f,z,ma-6+b,mb-6+b,270,False,0.8+cs)
        else:
            s=ar(t) if p["arabic"][i] else tx(t,i,p);put_line(c,s,f,z,cs,b)
    if p.get("star"):
        yy=g["inner"][1]*0.5;pa=c.beginPath()
        for k in range(10):
            a=math.radians(90+k*36);rr=6.5 if k%2==0 else 2.6;pt=(rr*math.cos(a),yy+rr*math.sin(a));(pa.moveTo if k==0 else pa.lineTo)(*pt)
        pa.close();c.drawPath(pa,fill=1,stroke=0)
    c.restoreState()

def make_identity(shape,idx,r):
    pre,sh=r.choice(PREF),r.choice(SHORT);org=f"{pre} {sh}";city=r.choice(CITY)
    ifn="I.F. : %07d %s/%s/000"%(r.randrange(1000000,9999999),r.choice("ABCD"),r.choice("MP"))
    date=f"{r.randrange(1,29):02d} {r.choice(MON)} {r.choice([2023,2024,2025])}"
    heavy,light=r.choice(FONTSETS);col=list(r.choice(COLORS));alpha=round(r.uniform(.78,.9),2)
    p=dict(shape=shape,ink=[round(v,3) for v in col],alpha=alpha,rot=round(r.uniform(-6,6),2),dx=0.0,dy=0.0,dash="-",star=False)
    arabic=r.random()<.33
    if shape in("oval","circle"):
        center=[(ifn,light,8,False),(date,heavy,9.5,False),("SPÉCIMEN / FAUX",heavy,8.5,False)]
        if arabic: center.append(("نموذج وهمي","Ar",8,True))
        elif r.random()<.5: center.append(("NE PAS UTILISER",light,7,False))
        if shape=="oval":
            ao=r.uniform(86,100);bo=ao*r.uniform(.60,.68);g=dict(outer=[ao,bo],mid=[ao-6,bo-6],inner=[ao-28,bo-26],lw=[round(r.uniform(1.8,2.6),2),round(r.uniform(.7,1.0),2),round(r.uniform(.8,1.2),2)])
        else:
            ro=r.uniform(52,62);g=dict(outer=[ro,ro],mid=[ro-5,ro-5],inner=[ro*.58,ro*.58],lw=[round(r.uniform(1.8,2.6),2),round(r.uniform(.7,1.0),2),round(r.uniform(.8,1.2),2)])
            p["star"]=r.random()<.45 and len(center)<=3
        arcs=[(org,heavy,8,"arc_top"),(f"{city.upper()} - TUNISIE",heavy,8,"arc_bot")]
        for k,(t,f,z,role) in enumerate(arcs):
            a_,b_=(g["inner"][0]+4.5,g["inner"][1]+4.5) if role=="arc_top" else (g["mid"][0]-6,g["mid"][1]-6)
            arcs[k]=(t,f,fit(t,f,z,a_,b_),role)
        m=len(center);sp=11 if m>2 else 12;off=-6 if p["star"] else 0;ys=[(m-1)/2*sp-i*sp-3+off for i in range(m)]
        lines=[(t,f,z,"arc",False,0) for t,f,z,_ in arcs]
        roles=["arc_top","arc_bot"]+["line"]*m;texts=[a[0] for a in arcs]+[c_[0] for c_ in center]
        fonts=[a[1] for a in arcs]+[c_[1] for c_ in center];sizes=[a[2] for a in arcs]+[c_[2] for c_ in center]
        base=[0,0]+[round(y,2) for y in ys];ar_=[False,False]+[c_[3] for c_ in center];p["geo"]=g
    else:
        L=[(org,heavy,9.5,False),(f"{city} - Tunisie",light,8.5,False),(ifn,light,8.5,False),(date,heavy,10,False),("SPÉCIMEN / FAUX",heavy,8.5,False)]
        if arabic: L.insert(4,("نموذج وهمي","Ar",8.5,True))
        if shape=="text": L=L[:5] if not arabic else L[:6]
        m=len(L);sp=13;ys=[(m-1)/2*sp-i*sp-3 for i in range(m)]
        texts=[l[0] for l in L];fonts=[l[1] for l in L];sizes=[l[2] for l in L];roles=["line"]*m;base=[round(y,2) for y in ys];ar_=[l[3] for l in L]
        if shape=="rect":
            wmax=max(stringWidth(t,f,z) for t,f,z,a in L if not a);sw=min(230,max(150,wmax+26))
            p["geo"]=dict(sw=round(sw,1),sh=round(m*sp+18,1),lw=[round(r.uniform(1.8,2.6),2),round(r.choice([0,r.uniform(.7,1.0)]),2),],inset=round(r.uniform(3,5),1))
            p["geo"]["lw"]=[p["geo"]["lw"][0],p["geo"]["lw"][1]] if len(p["geo"]["lw"])==2 else p["geo"]["lw"]
        else: p["geo"]={}
    n=len(texts);p.update(texts=texts,roles=roles,arabic=ar_,fonts=fonts,sizes=sizes,cs=[0]*n,base=base,accents=[True]*n)
    return org,city,p

# ---------- mutators ----------
def make_mutators(REF,shape):
    n=len(REF["texts"]);nonar=[i for i in range(n) if not REF["arabic"][i]]
    acc=[i for i in nonar if REF["texts"][i]!=REF["texts"][i].translate(ACC_MAP)];hasdash=any(" - " in REF["texts"][i] for i in nonar)
    def size(p,r,m): i=r.choice(nonar);d=r.choice([-1,1])*r.uniform(.3,.8)*m;p["sizes"][i]=round(p["sizes"][i]+d,2);return "size",f"line{i+1} {d:+.2f}pt"
    def spacing(p,r,m): i=r.choice(nonar);d=r.uniform(.15,.4)*m;p["cs"][i]=round(d,3);return "letter_spacing",f"line{i+1} +{d:.2f}pt"
    def font(p,r,m): i=r.choice(nonar);alt=r.choice(ALT[REF["fonts"][i]]);p["fonts"][i]=alt;return "font_substitution",f"line{i+1} {REF['fonts'][i]}->{alt}"
    def accent(p,r,m): i=r.choice(acc);p["accents"][i]=False;return "dropped_accents",f"line{i+1}"
    def base(p,r,m): i=r.randrange(n);d=r.choice([-1,1])*r.uniform(.8,2.2)*m;p["base"][i]=round(p["base"][i]+d,2);return "baseline_shift",f"line{i+1} {d:+.2f}pt"
    def rot(p,r,m): d=r.choice([-1,1])*r.uniform(.7,2.0)*m;p["rot"]=round(p["rot"]+d,2);return "rotation",f"{d:+.2f}deg"
    def off(p,r,m): dx,dy=[r.choice([-1,1])*r.uniform(1,4)*m for _ in range(2)];p["dx"],p["dy"]=round(dx,2),round(dy,2);return "offset",f"dx{dx:+.2f} dy{dy:+.2f}pt"
    def ink(p,r,m):
        p["ink"]=[round(min(1,max(0,v+r.choice([-1,1])*r.uniform(.02,.06)*m)),3) for v in p["ink"]];p["alpha"]=round(min(1,max(.5,p["alpha"]+r.choice([-1,1])*r.uniform(.04,.1)*m)),3);return "ink_shade",f"rgb{p['ink']} a={p['alpha']}"
    def dash(p,r,m): p["dash"]="–";return "dash_variant","hyphen->en dash"
    def geo(p,r,m):
        g=p["geo"]
        if shape in("oval","circle"):
            k=r.choice([-1,1])*r.uniform(.03,.08)*m;sx=1+k;sy=1+(k if shape=="circle" else k*r.choice([-1,1,.4]))
            for key in("outer","mid"): g[key]=[round(g[key][0]*sx,2),round(g[key][1]*sy,2)]
            g["lw"][0]=round(max(.8,g["lw"][0]+r.choice([-1,1])*r.uniform(.2,.5)*m),2);return "geometry",f"scale x{sx:.3f} y{sy:.3f} lw {g['lw'][0]}"
        dw=r.choice([-1,1])*r.uniform(2,6)*m;dh=r.choice([-1,1])*r.uniform(1,4)*m;g["sw"]=round(g["sw"]+dw,1);g["sh"]=round(g["sh"]+dh,1)
        g["lw"][0]=round(max(.8,g["lw"][0]+r.choice([-1,1])*r.uniform(.2,.5)*m),2);return "geometry",f"rect {dw:+.1f}x{dh:+.1f} lw {g['lw'][0]}"
    allm=[size,spacing,font,base,rot,off,ink]+([accent] if acc else [])+([dash] if hasdash else [])+([geo] if shape!="text" else [])
    sub=[size,spacing,base,rot,off,ink]+([geo] if shape!="text" else [])
    return {"subtle":(.5,[1],sub),"medium":(1.,[1,2],allm),"obvious":(2.,[2,3,4],allm)}

# ---------- rendering ----------
K=None
def stamp_png(p,dpi,tmp):
    pdf=os.path.join(tmp,"s.pdf");c=canvas.Canvas(pdf,pagesize=(260,190));draw_stamp(c,p,130,95);c.save()
    subprocess.run(["pdftoppm","-r",str(dpi),"-png","-singlefile",pdf,os.path.join(tmp,"s")],check=True);return Image.open(os.path.join(tmp,"s.png")).convert("RGB")
PHR=["Pour la Direction,","Le Responsable du Service,","Fait à {c}, pour servir et valoir ce que de droit.","Le Chef de Département,","Pour avis conforme,"]
def page_patch(dpi,r,city):
    k=dpi/72;W,H=int(340*k),int(240*k);bg=(r.randint(244,255),r.randint(242,252),r.randint(236,250));img=Image.new("RGB",(W,H),bg);d=ImageDraw.Draw(img)
    f=ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",int(11*k))
    d.text((int(18*k),int(14*k)),r.choice(PHR).format(c=city),fill=(35,35,35),font=f)
    if r.random()<.6: d.text((int(18*k),int(30*k)),r.choice(PHR).format(c=city),fill=(60,60,60),font=f)
    x0,y0=int(r.uniform(20,150)*k),int(r.uniform(150,200)*k);pts=[];sc=(r.choice([(20,30,90),(20,20,20),(40,30,110)]))
    for t in range(26): pts.append((x0+t*3.4*k+math.sin(t*r.uniform(.5,.9))*6*k,y0+math.sin(t*r.uniform(.3,.6)+r.uniform(0,3))*9*k))
    d.line(pts,fill=sc,width=max(2,int(1.4*k)),joint="curve");return img
def degrade(img,r):
    if r.random()<.25: img=img.convert("L").convert("RGB")
    if r.random()<.5: s=r.uniform(.5,.9);w,h=img.size;img=img.resize((int(w*s),int(h*s)),Image.BILINEAR).resize((w,h),Image.BILINEAR)
    if r.random()<.6: img=img.rotate(r.uniform(-3,3),resample=Image.BICUBIC,fillcolor=(250,248,244))
    if r.random()<.6: img=img.filter(ImageFilter.GaussianBlur(r.uniform(.3,1.2)))
    a=np.asarray(img).astype(np.float32)
    if r.random()<.5: t=r.uniform(0,10);a[...,2]-=t;a[...,1]-=t*.4
    a=(a-128)*r.uniform(.85,1.15)+128+r.uniform(-18,12)
    if r.random()<.7: a+=np.random.default_rng(r.randrange(1<<30)).normal(0,r.uniform(2,8),a.shape)
    q=r.randint(40,90);return Image.fromarray(np.clip(a,0,255).astype(np.uint8)),q
def render(p,dpi,r,city,path,tmp,clean=False):
    st=stamp_png(p,dpi,tmp);pg=page_patch(dpi,r,city);k=dpi/72
    ox,oy=int(r.uniform(-14,14)*k*.3),int(r.uniform(-8,8)*k*.3);pos=(int(pg.width/2-st.width/2+ox+20*k*.4),int(pg.height/2-st.height/2+oy))
    region=pg.crop((pos[0],pos[1],pos[0]+st.width,pos[1]+st.height));mul=Image.fromarray((np.asarray(region).astype(np.float32)*np.asarray(st.crop((0,0,region.width,region.height))).astype(np.float32)/255).astype(np.uint8))
    pg.paste(mul,pos)
    if clean: pg.save(path,quality=95);return dict(jpeg_q=95,degraded=False)
    img,q=degrade(pg,r);img.save(path,quality=q);return dict(jpeg_q=q,degraded=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--out",default="dataset");ap.add_argument("--counterfeit",type=int,default=40);ap.add_argument("--harmless",type=int,default=10)
    ap.add_argument("--seed",type=int,default=42);ap.add_argument("--dpi",type=int,default=120);ap.add_argument("--v2",default="../stamp_dataset_v2/dataset_all");a=ap.parse_args()
    r=random.Random(a.seed);tmp=tempfile.mkdtemp();os.makedirs(a.out+"/images",exist_ok=True)
    ids=[];orgs=set()
    for fam,cnt in FAMS.items():
        for j in range(1,cnt+1):
            while True:
                org,city,p=make_identity(fam,j,r)
                if org not in orgs: orgs.add(org);break
            ids.append((f"{fam}_{j:02d}",fam,org,city,p))
    orig={"orig_capital":"oval","orig_subvention":"rect","orig_labellisation":"circle","orig_balance":"text"}
    # identity-level split (30 identities, stratified by family): train/val/test counts per family
    CNT={"oval":(5,1,2),"rect":(4,2,2),"circle":(5,2,1),"text":(4,1,1)};split={}
    for fam,(ntr,nva,nte) in CNT.items():
        pool=[i[0] for i in ids if i[1]==fam]+[k for k,v in orig.items() if v==fam];r.shuffle(pool)
        for k,s in zip(pool,["train"]*ntr+["val"]*nva+["test"]*nte): split[k]=s
    rows=[]
    for iid,fam,org,city,REF in ids:
        mut=make_mutators(REF,fam);gid=f"{iid}_gen_000";aug=render(REF,a.dpi,r,city,f"{a.out}/images/{gid}.jpg",tmp,clean=True)
        base=dict(identity_id=iid,family=fam,organization=org,source_dataset="v3",split=split[iid],parent_reference=gid)
        rows.append(dict(base,id=gid,image=f"images/{gid}.jpg",kind="genuine",difficulty="none",mutations="[]",stamp_params=json.dumps(REF,ensure_ascii=False),**aug))
        for n in range(a.harmless):
            sid=f"{iid}_har_{n:03d}";aug=render(REF,a.dpi,r,city,f"{a.out}/images/{sid}.jpg",tmp)
            rows.append(dict(base,id=sid,image=f"images/{sid}.jpg",kind="genuine_variant",difficulty="none",mutations="[]",stamp_params=json.dumps(REF,ensure_ascii=False),**aug))
        for n in range(a.counterfeit):
            diff=["subtle","medium","obvious"][n%3];m,ks,pool=mut[diff];p=copy.deepcopy(REF);ms=[f(p,r,m) for f in r.sample(pool,min(r.choice(ks),len(pool)))]
            sid=f"{iid}_cfr_{n:03d}";aug=render(p,a.dpi,r,city,f"{a.out}/images/{sid}.jpg",tmp)
            rows.append(dict(base,id=sid,image=f"images/{sid}.jpg",kind="counterfeit",difficulty=diff,mutations=json.dumps([f"{x}:{y}" for x,y in ms],ensure_ascii=False),stamp_params=json.dumps(p,ensure_ascii=False),**aug))
    # originals from v2 (stamp crops copied in)
    if os.path.isdir(a.v2):
        names={"balance":("orig_balance","BMC (text-only blue)"),"capital":("orig_capital","BPAE (oval blue)"),"subvention":("orig_subvention","FRAI (rect violet)"),"labellisation":("orig_labellisation","Comité de Labellisation (round raster)")}
        for row in csv.DictReader(open(a.v2+"/labels_all.csv",encoding="utf-8")):
            iid,org=names[row["doc"]];dst=f"originals/{row['doc']}";os.makedirs(f"{a.out}/{dst}",exist_ok=True);fn=os.path.basename(row["crop"]);shutil.copy(f"{a.v2}/{row['crop']}",f"{a.out}/{dst}/{fn}")
            rows.append(dict(identity_id=iid,family=orig[iid],organization=org,source_dataset="v2",split=split[iid],parent_reference=f"{iid} (uploaded original PDF)",id=row["id"],image=f"{dst}/{fn}",
                kind="genuine_variant" if row["label"]=="reference" else "counterfeit",difficulty=row["difficulty"] if row["label"]=="counterfeit" else "none",mutations=row["mutations"],stamp_params=row["stamp_params"],jpeg_q=row["jpeg_q"],degraded=True))
    with open(a.out+"/manifest.csv","w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(len(rows),"rows;",len(set(x["identity_id"] for x in rows)),"identities")
if __name__=="__main__": main()

"use strict";
const $ = (selector) => document.querySelector(selector);
const attachments = [];
let types = [];
const savedTerms = {};
let activeContractType = "";
function node(tag, text, className) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(className)n.className=className; return n; }
function profile() { return Object.fromEntries([...new FormData($("#profile-form")).entries()].filter(([,v])=>v.trim())); }
async function api(path, options={}) { const response=await fetch(path,options); const body=await response.json(); if(!response.ok)throw new Error(typeof body.detail==="string"?body.detail:JSON.stringify(body.detail)); return body; }
const post = (path, body) => api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
const guidanceModes={grounded_answer:"Réponse étayée par les sources",evidence_only:"Passages des sources · réponse générée indisponible",needs_info:"Précisions nécessaires",abstained:"Sources insuffisantes"};
api("/api/legal/status").then(status=>{
  const mode=status.hosted_llm_configured?"Traitement cloud configuré : les textes des demandes peuvent être transmis au fournisseur.":status.local_llm_configured?"Modèle local configuré.":"Lecture des sources et trames de contrats disponibles sans modèle de génération.";
  $("#runtime-status").textContent=`${mode} ${status.legal_documents} sources juridiques · ${status.contract_types} types de contrats.`;
}).catch(()=>{$("#runtime-status").textContent="Service indisponible. Démarrez l'application locale.";});
function view(name) { for(const tab of document.querySelectorAll("[data-view]")){const active=tab.dataset.view===name;tab.classList.toggle("is-active",active);tab.setAttribute("aria-pressed",String(active));} $("#guidance").hidden=name!=="guidance";$("#contracts").hidden=name!=="contracts"; }
for(const tab of document.querySelectorAll("[data-view]"))tab.addEventListener("click",()=>{location.hash=tab.dataset.view;view(tab.dataset.view);});
window.addEventListener("hashchange",()=>view(location.hash==="#contracts"?"contracts":"guidance"));
view(location.hash==="#contracts"?"contracts":"guidance");
function party() { const area=$("#parties"); if(area.children.length>=12)return; const row=node("div",undefined,"party"); for(const [key,label] of [["name","Nom / raison sociale"],["role","Rôle"],["address","Adresse"]]){const wrap=node("label",label,key==="address"?"address":"");const input=document.createElement("input");input.type="text";input.dataset.field=key;input.maxLength=500;wrap.append(input);row.append(wrap);} const remove=node("button","Retirer","secondary");remove.type="button";remove.addEventListener("click",()=>row.remove());row.append(remove);area.append(row); }
$("#add-party").addEventListener("click",party);party();party();
for(const [button,key] of [["#profile-name","founder_name"],["#profile-company","company_name"],["#profile-context","project_summary"]]){
  $(button).addEventListener("click",()=>{
    const value=profile()[key];
    if(!value){$("#profile-copy-status").textContent="Complétez cette information dans le profil de fondateur.";return;}
    if(key==="project_summary")$("#purpose").value=value;
    else {if(!$("#parties").children.length)party();$("#parties [data-field=name]").value=value;}
    $("#profile-copy-status").textContent="Information reprise du profil. Vérifiez l'identité, le rôle et les autres modalités avant de préparer le projet.";
  });
}
async function loadTypes(){ const current=$("#contract-type").value; types=(await api(`/api/legal/contracts/types?language=${$("#language").value}`)).types; $("#contract-type").replaceChildren();for(const type of types){const option=node("option",type.title);option.value=type.id;$("#contract-type").append(option);}if(types.some(t=>t.id===current))$("#contract-type").value=current;renderFields(); }
function renderFields(){
  const type=types.find(t=>t.id===$("#contract-type").value);if(!type)return;
  if(activeContractType)savedTerms[activeContractType]=Object.fromEntries([...document.querySelectorAll("[data-term]")].map(input=>[input.dataset.term,input.value]));
  activeContractType=type.id;
  $("#contract-fields").replaceChildren();
  for(const field of type.fields){
    const label=node("label",field.label), input=document.createElement(field.id==="disclosure_mode"?"select":"textarea");
    if(field.id==="disclosure_mode"){
      for(const [value,text] of [["","Choisir"],["mutual","mutual — réciproque"],["one_way","one_way — unilatéral"]]){const option=node("option",text);option.value=value;input.append(option);}
      label.append(node("small","Pour un accord unilatéral, indiquez les rôles discloser et recipient dans les parties."));
    } else {input.rows=2;input.maxLength=4000;}
    input.dataset.term=field.id;input.value=savedTerms[type.id]?.[field.id]||"";
    label.append(input);$("#contract-fields").append(label);
  }
  $("#equity-label").hidden=!type.equity_required;$("#suggestions").replaceChildren();
}
$("#contract-type").addEventListener("change",renderFields);
$("#language").addEventListener("change",()=>loadTypes().catch(showInitError));
function sourceList(citations){
  const list=node("ol",undefined,"sources");
  for(const c of citations||[]){
    const item=node("li"), web=c.extraction_method==="web";
    const a=node("a",`[${c.ref}] ${c.title} — ${web?"page WIPO":`${c.article?"art. "+c.article+", ":""}p. ${c.page}`}`);
    a.href=web&&/^https:\/\/www\.wipo\.int\/wipolex\//.test(c.publisher_url||"")?c.publisher_url:`/api/legal/sources/document?doc_id=${encodeURIComponent(c.doc_id)}#page=${c.page}`;
    a.target="_blank";a.rel="noopener";
    item.append(a,node("blockquote",c.quote));
    if(c.source_kind==="educational_guide")item.append(node("small","Guide pédagogique — ne constitue pas une loi."));
    if(c.extraction_method==="ocr")item.append(node("small","Transcription OCR — vérifier les mots et chiffres dans le PDF."));
    if(c.retrieved_at)item.append(node("small",`Consulté : ${new Date(c.retrieved_at).toLocaleDateString()}`));
    list.append(item);
  }
  return list;
}
$("#upload-form").addEventListener("submit",async event=>{event.preventDefault();const status=$("#upload-status"),button=event.currentTarget.querySelector("button");if(attachments.length>=3){status.textContent="Limite de 3 documents atteinte. Retirez un document.";return;}const file=$("#upload").files[0];if(!file)return;if(file.size>10*1024*1024){status.textContent="Le fichier dépasse 10 Mo.";return;}button.disabled=true;status.textContent="Lecture locale du document…";try{const form=new FormData();form.append("file",file);form.append("local_ocr",String($("#local-ocr").checked));if(file.name.toLowerCase().endsWith(".pdf")){form.append("page_start",$("#page-start").value||"1");if($("#page-end").value)form.append("page_end",$("#page-end").value);}const result=await api("/api/legal/documents/extract",{method:"POST",body:form});attachments.push(result.attachment);const item=node("details",undefined,"document");item.append(node("summary",result.attachment.filename),node("pre",result.attachment.text||"Aucun texte exploitable."));for(const warning of result.warnings)item.append(node("p",warning,"notice"));const remove=node("button","Retirer de la demande","secondary");remove.type="button";remove.addEventListener("click",()=>{attachments.splice(attachments.indexOf(result.attachment),1);item.remove();});item.append(remove);$("#document-list").append(item);status.textContent="Document ajouté à cette demande.";}catch(error){status.textContent=error.message;}finally{button.disabled=false;}});
$("#guidance-form").addEventListener("submit",async event=>{event.preventDefault();const result=$("#guidance-result"),button=event.currentTarget.querySelector("button");result.replaceChildren(node("p","Recherche des textes et vérification des affirmations…"));button.disabled=true;try{const body=await post("/api/legal/guidance",{question:$("#legal-question").value,language:$("#language").value,jurisdiction:$("#guidance-jurisdiction").value,profile:profile(),attachments});result.replaceChildren(node("p",guidanceModes[body.mode]||body.mode,"pill"));const answer=node("pre",body.result.answer);answer.dir=$("#language").value==="ar"?"rtl":"auto";result.append(answer,sourceList(body.result.citations));for(const point of [...body.result.missing_info,...body.limitations])result.append(node("p",point,"notice"));for(const url of body.research_links){const a=node("a",url);a.href=url;a.target="_blank";a.rel="noopener";result.append(a,node("br"));}}catch(error){result.textContent=error.message;}finally{button.disabled=false;}});
$("#checklist").addEventListener("click",async event=>{const button=event.currentTarget,result=$("#guidance-result");button.disabled=true;result.textContent="Recherche des étapes étayées…";try{const body=await post("/api/legal/checklists",{task:$("#checklist-task").value,language:$("#language").value,jurisdiction:$("#guidance-jurisdiction").value,profile:profile()});result.replaceChildren();if(body.steps.length){for(const step of body.steps){const label=node("label",undefined,"checkbox");const box=document.createElement("input");box.type="checkbox";label.append(box,node("span",step.text+" ["+step.refs.join(", ")+"]"));result.append(label);}}else result.append(node("pre",body.guidance.result.answer));result.append(sourceList(body.guidance.result.citations));for(const note of body.guidance.limitations)result.append(node("p",note,"notice"));}catch(error){result.textContent=error.message;}finally{button.disabled=false;}});
function requestBody(){let equity=[];if(!$("#equity-label").hidden&&$("#equity").value.trim()){equity=$("#equity").value.trim().split(/\r?\n/).map(line=>{const at=line.lastIndexOf(":");if(at<1)throw new Error("Répartition : utilisez « nom : pourcentage ».");const percentage=Number(line.slice(at+1).trim().replace("%","").replace(",","."));if(!Number.isFinite(percentage))throw new Error("Pourcentage invalide.");return {party:line.slice(0,at).trim(),percentage};});}return {contract_type:$("#contract-type").value,language:$("#language").value,jurisdiction:$("#contract-jurisdiction").value,effective_date:$("#effective-date").value||null,purpose:$("#purpose").value,parties:[...document.querySelectorAll(".party")].map(row=>Object.fromEntries([...row.querySelectorAll("[data-field]")].map(input=>[input.dataset.field,input.value]))),terms:Object.fromEntries([...document.querySelectorAll("[data-term]")].map(input=>[input.dataset.term,input.value])),equity,profile:profile(),attachments,refine_with_llm:$("#refine").checked,export_docx:true};}
$("#suggest").addEventListener("click",async event=>{const result=$("#suggestions");result.textContent="Recherche de propositions attribuées aux documents…";event.currentTarget.disabled=true;try{const response=await post("/api/legal/contracts/suggest",requestBody());result.replaceChildren();if(!response.suggestions.length)result.append(node("p",response.message||"Aucune proposition étayée. Consultez le texte extrait.","notice"));for(const suggestion of response.suggestions){const item=node("div",undefined,"notice");item.append(node("p",`${suggestion.field} : ${suggestion.value}`),node("blockquote",`${suggestion.source_file} — ${suggestion.quote}`));const apply=node("button","Confirmer et utiliser ce texte","secondary");apply.type="button";apply.addEventListener("click",()=>{const target=suggestion.field==="purpose"?$("#purpose"):[...document.querySelectorAll("[data-term]")].find(i=>i.dataset.term===suggestion.field);if(target)target.value=suggestion.value;apply.disabled=true;apply.textContent="Confirmé";});item.append(apply);result.append(item);}}catch(error){result.textContent=error.message;}finally{event.target.disabled=false;}});
$("#contract-form").addEventListener("submit",async event=>{event.preventDefault();const result=$("#contract-result"),button=event.currentTarget.querySelector('button[type="submit"]');button.disabled=true;result.textContent="Préparation du projet et contrôle des modalités…";try{const body=await post("/api/legal/contracts/draft",requestBody());result.replaceChildren(node("p",body.status==="needs_info"?"Informations à compléter":body.mode==="llm_refined"?"Projet à relire · rédaction IA":"Projet à relire · trame complétée","pill"));if(body.missing_fields.length){const list=node("ul");for(const field of body.missing_fields)list.append(node("li",field.question));result.append(list);return;}const preview=node("pre",body.document_text);preview.dir=body.language==="ar"?"rtl":"auto";result.append(preview);for(const point of body.review_points)result.append(node("p",point,"notice"));result.append(sourceList(body.source_citations));if(body.docx_base64){const download=node("button","Télécharger le projet Word","download");download.type="button";download.addEventListener("click",()=>{const bytes=Uint8Array.from(atob(body.docx_base64),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}));const a=document.createElement("a");a.href=url;a.download=body.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});result.append(download);}}catch(error){result.textContent=error.message;}finally{button.disabled=false;}});
function showInitError(error){$("#contract-result").textContent=error.message;}
loadTypes().catch(showInitError);

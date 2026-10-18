"""Build the n8n workflow JSON files from the readable sources in n8n/src/.

The JavaScript of the Code nodes lives in .js files so it can be read and
reviewed; this script embeds it. Run from the repository root:

    python n8n/src/build_workflows.py

Then import the JSON in n8n (Workflows > Import from File), or with
    docker exec law_rag-n8n-1 n8n import:workflow --input=/workflows/<file>.json
"""

import json
import pathlib

SRC = pathlib.Path(__file__).parent
OUT = SRC.parent


def code(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def node(name, type_, version, position, parameters, **extra):
    return {"parameters": parameters, "name": name, "type": f"n8n-nodes-base.{type_}", "typeVersion": version,
            "position": position, "id": name.lower().replace(" ", "-").replace("/", "-"), **extra}


def link(*targets):
    return {"main": [[{"node": t, "type": "main", "index": i} for t, i in targets]]}


def founder_intake() -> dict:
    stages = ["Idea", "Company creation", "Expansion", "Growth"]
    needs = ["Any support", "Loan", "Grant", "Loan guarantee", "Tax advantage", "Guidance"]
    # Form Trigger 2.1, not 2.2: 2.2 dropped "Respond When: Using Respond to Webhook node", which
    # lets the workflow answer the form with our HTML report (the form page shows any non-JSON reply).
    form = node("Founder intake form", "formTrigger", 2.1, [0, 300], {
        "path": "founder-intake",
        "formTitle": "Tunisian startup check-up",
        "formDescription": "Describe your project. You get, on one page, the legal form and creation steps "
                           "(from Tunisian official texts) and the funding programmes that may fit.",
        "formFields": {"values": [
            {"fieldLabel": "Describe your project", "fieldType": "textarea", "requiredField": True,
             "placeholder": "Example: a mobile app that connects farmers with restaurants"},
            {"fieldLabel": "Stage", "fieldType": "dropdown", "requiredField": True,
             "fieldOptions": {"values": [{"option": s} for s in stages]}},
            {"fieldLabel": "Sector", "placeholder": "technology, industry, agrifood, services…"},
            {"fieldLabel": "What do you need?", "fieldType": "dropdown",
             "fieldOptions": {"values": [{"option": n} for n in needs]}},
            {"fieldLabel": "Funding need (TND)", "fieldType": "number", "placeholder": "50000"},
            {"fieldLabel": "Governorate", "placeholder": "Tunis, Sfax, Kasserine…"},
            {"fieldLabel": "Answer language", "fieldType": "dropdown", "requiredField": True,
             "fieldOptions": {"values": [{"option": "English"}, {"option": "Français"}, {"option": "العربية"}]}},
        ]},
        "responseMode": "responseNode",
        "options": {},
    }, webhookId="6f0c2b1e-4d7a-4f3e-9a51-2c8e5d1f0a11")
    prepare = node("Prepare requests", "code", 2, [220, 300], {"jsCode": code("intake_prepare.js")})
    http_opts = {"timeout": 180000}
    aid = node("Funding eligibility", "httpRequest", 4.2, [460, 200], {
        "method": "POST",
        "url": "={{ $env.API_BASE_URL }}/api/aid/match",
        "sendHeaders": True,
        "headerParameters": {"parameters": [{"name": "X-Session-Id", "value": "={{ $json.request_id }}"}]},
        "sendBody": True, "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify($json.aid) }}",
        "options": http_opts,
    }, onError="continueRegularOutput")
    chat = node("Legal question", "httpRequest", 4.2, [460, 400], {
        "method": "POST",
        "url": "={{ $env.API_BASE_URL }}/api/chat",
        "sendBody": True, "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ question: $json.question, session_id: $json.request_id, channel: 'n8n-form' }) }}",
        "options": http_opts,
    }, onError="continueRegularOutput")
    merge = node("Wait for both", "merge", 3.1, [700, 300], {})
    report = node("Build report", "code", 2, [920, 300], {"jsCode": code("intake_report.js")})
    respond = node("Show report", "respondToWebhook", 1.1, [1160, 200], {
        "respondWith": "text",
        "responseBody": "={{ $json.html }}",
        "options": {"responseHeaders": {"entries": [{"name": "Content-Type", "value": "text/html; charset=utf-8"}]}},
    })
    to_file = node("Record as JSON", "convertToFile", 1.1, [1160, 400], {
        "operation": "toJson", "mode": "each",
        "options": {"format": True, "fileName": "={{ $json.record.request_id }}.json"},
    })
    save = node("Save record", "readWriteFile", 1, [1380, 400], {
        "operation": "write",
        "fileName": "=/files/intake/{{ $('Build report').item.json.record.request_id }}.json",
        "dataPropertyName": "data",
        "options": {},
    }, onError="continueRegularOutput")
    nodes = [form, prepare, aid, chat, merge, report, respond, to_file, save]
    return {
        "name": "Founder intake form",
        "nodes": nodes,
        "connections": {
            form["name"]: link((prepare["name"], 0)),
            prepare["name"]: link((aid["name"], 0), (chat["name"], 0)),
            aid["name"]: link((merge["name"], 0)),
            chat["name"]: {"main": [[{"node": merge["name"], "type": "main", "index": 1}]]},
            merge["name"]: link((report["name"], 0)),
            report["name"]: link((respond["name"], 0), (to_file["name"], 0)),
            to_file["name"]: link((save["name"], 0)),
        },
        "settings": {"executionOrder": "v1"},
        "active": False,
        "pinData": {},
    }


if __name__ == "__main__":
    for filename, build in [("founder_intake_form.json", founder_intake)]:
        (OUT / filename).write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("wrote", OUT / filename)

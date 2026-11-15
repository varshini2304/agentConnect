from io import BytesIO

from docx import Document


def _draft(**overrides):
    return {
        "name": "Support guide agent", "description": "Answers from the company support guide.",
        "role": "Support assistant", "domain": "Customer support",
        "purpose": "Explain the documented support process.", "responsibilities": [], "helps_with": [],
        "must_not_do": [], "expected_outcomes": [], "categories": ["customer_support"],
        "topics": ["refunds"], "keywords": ["receipt"], "discussion_topics": ["refunds"],
        "knowledge_text": "Refunds require the receipt.", **overrides,
    }


def test_markdown_generates_profile_and_preserves_extracted_text(client, monkeypatch):
    seen = {}

    def fake_generate(source, mime_type, company_name):
        seen.update(source=source, mime_type=mime_type, company_name=company_name)
        return _draft()

    monkeypatch.setattr("app.services.agent_generation.draft_agent_from_document", fake_generate)
    response = client.post("/api/v1/agents/generate-from-document", files={
        "document": ("support-guide.md", b"# Refunds\nKeep the receipt for 30 days.", "text/markdown"),
    })
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Support guide agent"
    assert response.json()["knowledge_text"] == "# Refunds\nKeep the receipt for 30 days."
    assert seen["mime_type"] == "text/markdown"
    assert "Keep the receipt" in seen["source"]


def test_docx_text_is_extracted_before_gemini_draft(client, monkeypatch):
    buffer = BytesIO()
    doc = Document()
    doc.add_paragraph("Refunds require the original receipt.")
    doc.save(buffer)
    seen = {}

    def fake_generate(source, mime_type, company_name):
        seen.update(source=source, mime_type=mime_type)
        return _draft()

    monkeypatch.setattr("app.services.agent_generation.draft_agent_from_document", fake_generate)
    response = client.post("/api/v1/agents/generate-from-document", files={
        "document": ("support-guide.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    })
    assert response.status_code == 200, response.text
    assert seen["mime_type"] == "text/plain"
    assert "Refunds require the original receipt." in seen["source"]
    assert "Refunds require the original receipt." in response.json()["knowledge_text"]


def test_pdf_is_sent_as_a_document_part(client, monkeypatch):
    seen = {}

    def fake_generate(source, mime_type, company_name):
        seen.update(source=source, mime_type=mime_type)
        return _draft()

    monkeypatch.setattr("app.services.agent_generation.draft_agent_from_document", fake_generate)
    payload = b"%PDF-1.4\nminimal test payload"
    response = client.post("/api/v1/agents/generate-from-document", files={
        "document": ("support-guide.pdf", payload, "application/pdf"),
    })
    assert response.status_code == 200, response.text
    assert seen == {"source": payload, "mime_type": "application/pdf"}


def test_unknown_document_type_is_rejected_before_model_call(client):
    response = client.post("/api/v1/agents/generate-from-document", files={
        "document": ("notes.rtf", b"{\\rtf1 unsupported}", "application/rtf"),
    })
    assert response.status_code == 415

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import io, re
import fitz
from docx import Document

BASE = Path(__file__).parent
STATIC = BASE / "static"
app = FastAPI(title="ATS Resume Parser Demo")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "React", "Node.js", "FastAPI",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "Jenkins",
    "Git", "SQL", "PostgreSQL", "MongoDB", "Linux", "CI/CD", "REST", "GraphQL",
    "C", "C++", "C#", "Go", "Rust", "Bash", "PowerShell", "Spring", "Django",
    "Flask", "Next.js", "Vue", "Angular", "Redis", "MySQL", "PyTorch", "TensorFlow"
]
SECTION_ALIASES = {
    "summary": ["summary", "professional summary", "profile", "objective"],
    "experience": ["experience", "work experience", "professional experience", "employment", "work history"],
    "education": ["education", "academic background", "academics"],
    "skills": ["skills", "technical skills", "technologies", "core skills"],
    "projects": ["projects", "technical projects", "personal projects"],
    "certifications": ["certifications", "certificates", "licenses & certifications", "licenses and certifications"],
    "awards": ["awards", "honors", "achievements"],
}


def extract_pdf(data: bytes) -> str:
    doc = fitz.open(stream=data, filetype="pdf")
    return "\n".join(page.get_text("text") for page in doc)


def extract_docx(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def normalize_heading(raw_line: str) -> str:
    return re.sub(r"[^a-z0-9 &+/.-]", "", raw_line.lower()).strip()


def heading_to_section(raw_line: str):
    line = normalize_heading(raw_line)
    for section, aliases in SECTION_ALIASES.items():
        if line in aliases:
            return section
    return None


def split_sections(text: str):
    sections = {"header": []}
    current = "header"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        section = heading_to_section(line)
        if section:
            current = section
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if v}


def find_sections(text: str):
    return [k for k in split_sections(text).keys() if k != "header"]


def first_email(text: str):
    m = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
    return m.group(0) if m else None


def first_phone(text: str):
    m = re.search(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}", text)
    return m.group(0) if m else None


def find_linkedin(text: str):
    """Extract LinkedIn profile URL from resume text."""
    patterns = [
        r"(?:https?://)?(?:www\.)?linkedin\.com/(?:in|company)/[^\s/]+",
        r"linkedin\.com/in/[^\s]+"
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            url = m.group(0).rstrip(".,;)")
            if not url.startswith("http"):
                url = "https://" + url
            return url
    return None


def find_links(text: str):
    urls = re.findall(r"(?:https?://|www\.)[^\s|]+", text, flags=re.I)
    out = []
    for u in urls:
        u = u.rstrip(".,;)")
        if u not in out:
            out.append(u)
    return out[:8]


def find_dates(text: str):
    months = r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
    pattern = rf"(?:{months})\s+\d{{4}}|\b(?:19|20)\d{{2}}\b"
    vals = re.findall(pattern, text, flags=re.I)
    vals = [m.group(0) for m in re.finditer(pattern, text, flags=re.I)]
    out = []
    for v in vals:
        if v not in out:
            out.append(v)
    return out[:20]


def find_skills(text: str):
    low = text.lower()
    return [s for s in SKILLS if s.lower() in low]


def estimate_name(text: str):
    for line in text.splitlines()[:12]:
        line = line.strip()
        if not line or "@" in line or any(ch.isdigit() for ch in line):
            continue
        if heading_to_section(line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z.'-]+", w) for w in words):
            return line
    return None


def compact_section(value: str, max_chars: int = 3500) -> str:
    value = re.sub(r"[ \t]+", " ", value).strip()
    return value[:max_chars]


def validate_resume_contact_info(email: str, phone: str, linkedin: str) -> dict:
    """
    If all three are missing, print: Please enter a resume
    If one or more are missing, print: Please enter {missing items}
    """
    missing = []

    if not email:
        missing.append("email")
    if not phone:
        missing.append("phone number")
    if not linkedin:
        missing.append("LinkedIn account")

    if not missing:
        message = "All contact information found."
        status = "valid"
    elif len(missing) == 3:
        message = "Please enter a resume"
        status = "missing_all"
    else:
        message = "Please enter " + " and ".join(missing)
        status = "missing_some"

    return {
        "status": status,
        "missing": missing,
        "message": message,
    }


def build_ai_context(filename: str, text: str, parsed: dict, sections: dict) -> str:
    lines = [
        "# AI Resume Context",
        "",
        "> Compact, structured resume context generated locally for use with ChatGPT, Claude, or another AI.",
        "> Treat this as the source of truth for the candidate's resume. Do not invent missing details.",
        "",
        "## Candidate",
        f"- Name: {parsed.get('name') or 'Not detected'}",
        f"- Email: {parsed.get('email') or 'Not detected'}",
        f"- Phone: {parsed.get('phone') or 'Not detected'}",
    ]

    linkedin = parsed.get("linkedin")
    if linkedin:
        lines.append(f"- LinkedIn: {linkedin}")

    links = parsed.get("links") or []
    if links:
        lines.append("- Links: " + ", ".join(links))

    skills = parsed.get("skills") or []
    lines.extend(["", "## Skills", ", ".join(skills) if skills else "No skills confidently detected."])

    preferred_order = ["summary", "experience", "projects", "education", "certifications", "awards"]
    for section in preferred_order:
        content = sections.get(section)
        if content:
            lines.extend(["", f"## {section.title()}", compact_section(content)])

    header = sections.get("header", "")
    if header:
        header_lines = []
        name = parsed.get("name")
        email = parsed.get("email")
        phone = parsed.get("phone")
        for line in header.splitlines():
            if name and line.strip() == name.strip():
                continue
            if email and email in line:
                continue
            if phone and phone in line:
                continue
            header_lines.append(line)
        header_text = compact_section("\n".join(header_lines), 1500)
        if header_text:
            lines.extend(["", "## Additional Resume Details", header_text])

    lines.extend([
        "",
        "## Parsing Metadata",
        f"- Source file: {filename}",
        f"- Detected sections: {', '.join(parsed.get('sections') or []) or 'None'}",
        f"- Dates found: {', '.join(parsed.get('dates') or []) or 'None'}",
        "",
        "## Instructions for AI",
        "Use the information above when answering questions about this candidate. Preserve exact employers, projects, education, dates, technologies, and measurable outcomes as written. If a detail is not listed, do not invent it; tell the user it's not in the resume."
    ])
    return "\n".join(lines).strip() + "\n"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/parse")
async def parse_resume(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt"}:
        raise HTTPException(400, "Please upload a PDF, DOCX, or TXT resume.")
    data = await file.read()
    try:
        if suffix == ".pdf":
            text = extract_pdf(data)
        elif suffix == ".docx":
            text = extract_docx(data)
        else:
            text = data.decode("utf-8", errors="ignore")
    except Exception as exc:
        raise HTTPException(400, f"Could not read this file: {exc}")

    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    sections_map = split_sections(cleaned)
    sections = [k for k in sections_map.keys() if k != "header"]
    skills = find_skills(cleaned)
    dates = find_dates(cleaned)

    email = first_email(cleaned)
    phone = first_phone(cleaned)
    linkedin = find_linkedin(cleaned)

    contact_validation = validate_resume_contact_info(email, phone, linkedin)

    parsed = {
        "filename": file.filename,
        "characters": len(cleaned),
        "text_preview": cleaned[:1200],
        "name": estimate_name(cleaned),
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "links": find_links(cleaned),
        "sections": sections,
        "section_content": sections_map,
        "skills": skills,
        "dates": dates,
        "contact_validation": contact_validation,
    }
    parsed["ai_context"] = build_ai_context(file.filename or "resume", cleaned, parsed, sections_map)
    parsed["ai_context_chars"] = len(parsed["ai_context"])
    parsed["compression_ratio"] = round((len(parsed["ai_context"]) / len(cleaned)), 2) if cleaned else 0
    return parsed

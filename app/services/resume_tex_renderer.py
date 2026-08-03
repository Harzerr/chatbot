import io
import math
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "resume_master.tex"
MAX_COMPILE_SECONDS = 35

_TEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _escape_tex(value: Any) -> str:
    text = str(value or "")
    return "".join(_TEX_ESCAPES.get(char, char) for char in text).replace("\r", " ").replace("\n", " ").strip()


def _layout_value(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(minimum, min(maximum, parsed))


def _layout(content: dict[str, Any]) -> dict[str, Any]:
    value = content.get("layout")
    return value if isinstance(value, dict) else {}


def _section_style(content: dict[str, Any], key: str) -> tuple[float, int, str]:
    layout = _layout(content)
    styles = layout.get("sectionStyles") if isinstance(layout.get("sectionStyles"), dict) else {}
    style = styles.get(key) if isinstance(styles.get(key), dict) else {}
    size = _layout_value(style.get("fontSize", layout.get("fontSize", 10.5)), 10.5, 8, 16)
    weight = int(_layout_value(style.get("fontWeight", 400), 400, 400, 800))
    color = str(style.get("color") or "#17202a")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        color = "#17202a"
    return size, weight, color[1:]


def _styled_block(content: dict[str, Any], key: str, block: str) -> str:
    size, weight, color = _section_style(content, key)
    leading = size * 1.5
    weight_command = r"\bfseries" if weight >= 600 else r"\mdseries"
    return (
        "\\begingroup\n"
        f"\\fontsize{{{size:.1f}pt}}{{{leading:.2f}pt}}\\selectfont\n"
        f"\\renewcommand{{\\ResumeSectionFont}}{{\\fontsize{{{size:.1f}pt}}{{{leading:.2f}pt}}\\selectfont}}\n"
        f"{weight_command}\\color[HTML]{{{color}}}\n"
        f"{block}\n"
        "\\endgroup"
    )


def _items(items: list[Any]) -> str:
    rendered = []
    for item in items:
        value = item.get("text", "") if isinstance(item, dict) else item
        text = _escape_tex(value)
        if text:
            label = _escape_tex(item.get("label")) if isinstance(item, dict) else ""
            rendered.append(f"  \\item \\textbf{{{label}：}} {text}" if label else f"  \\item {text}")
    return "\\begin{ResumeItems}\n" + "\n".join(rendered) + "\n\\end{ResumeItems}" if rendered else ""


def _entries(entries: Any, heading: str) -> str:
    if not isinstance(entries, list) or not entries:
        return ""
    rendered: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = _escape_tex(entry.get("title"))
        subtitle = _escape_tex(entry.get("subtitle"))
        period = _escape_tex(entry.get("period"))
        if not title:
            continue
        rendered.append(f"\\ResumeEntry{{\\textbf{{{title}}}}}{{\\textbf{{{subtitle}}}}}{{{period}}}")
        summary = _escape_tex(entry.get("summary"))
        if summary:
            label = "项目简介" if heading == "项目经历" else "个人职责与成果"
            rendered.append(f"\\vspace{{3pt}}\n\\textbf{{{label}：}} {summary}\\par")
        tech_stack = entry.get("tech_stack")
        if isinstance(tech_stack, list):
            tech_stack = "、".join(_escape_tex(item) for item in tech_stack if _escape_tex(item))
        tech_stack = _escape_tex(tech_stack)
        if tech_stack:
            rendered.append(f"\\vspace{{3pt}}\n\\textbf{{技术栈：}} {tech_stack}\\par")
        items = _items(entry.get("items") if isinstance(entry.get("items"), list) else [])
        if items:
            label = "技术亮点" if heading == "项目经历" else "核心成果"
            rendered.append(f"\\vspace{{3pt}}\n\\textbf{{{label}：}}\\par\n\\vspace{{3pt}}\n" + items)
        rendered.append("\\vspace{6pt}")
    return "\n".join(rendered)


def _education(entries: Any) -> str:
    if not isinstance(entries, list) or not entries:
        return ""
    rendered: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("school"):
            continue
        program = " ".join(part for part in [_escape_tex(entry.get("major")), _escape_tex(entry.get("degree"))] if part)
        period = " - ".join(part for part in [_escape_tex(entry.get("start_date")), _escape_tex(entry.get("end_date"))] if part)
        rendered.append(f"\\ResumeEntry{{\\textbf{{{_escape_tex(entry.get('school'))}}}}}{{\\textbf{{{program}}}}}{{{period}}}")
        details = []
        if entry.get("rank"):
            details.append(f"综合排名：{_escape_tex(entry.get('rank'))}")
        if entry.get("gpa"):
            details.append(f"GPA：{_escape_tex(entry.get('gpa'))}")
        extra_details = str(entry.get("details") or "")
        english_level = str(entry.get("english_level") or "").strip()
        if not english_level:
            english_match = re.search(r"(?:英语水平|英语|English)\s*[:：]\s*([^；;\n]+)", extra_details, flags=re.IGNORECASE)
            if english_match:
                english_level = english_match.group(1).strip()
                extra_details = re.sub(r"(?:英语水平|英语|English)\s*[:：]\s*[^；;\n]+[；;]?", "", extra_details, flags=re.IGNORECASE).strip()
        if english_level:
            details.append(f"英语水平：{_escape_tex(english_level)}")
        if details:
            rendered.append("\\vspace{3pt}\n" + "\\quad ".join(details) + "\\par")
        if extra_details:
            rendered.append("\\vspace{3pt}\n" + _escape_tex(extra_details) + "\\par")
        rendered.append("\\vspace{6pt}")
    if not rendered:
        return ""
    return "\\ResumeSection[0pt]{教育背景}\n" + "\n".join(rendered)


def _content(content: dict[str, Any]) -> str:
    blocks: list[str] = []
    summary = _escape_tex(content.get("summary"))
    if summary:
        blocks.append(_styled_block(content, "summary", f"\\ResumeSection[0pt]{{职业摘要}}\n{summary}\\par"))
    education = _education(content.get("education"))
    if education:
        blocks.append(_styled_block(content, "education", education))
    headings: set[str] = set()
    for section in content.get("sections", []):
        if not isinstance(section, dict):
            continue
        heading = _escape_tex(section.get("heading"))
        entries = _entries(section.get("entries"), heading)
        items = _items(section.get("items") if isinstance(section.get("items"), list) else [])
        section_body = entries or items
        if not heading or not section_body or (education and heading == "教育背景"):
            continue
        headings.add(heading)
        blocks.append(_styled_block(content, section.get("heading") or "other", f"\\ResumeSection{{{heading}}}\n{section_body}"))

    skills = content.get("skills")
    if isinstance(skills, list) and skills and "专业技能" not in headings:
        items = _items(skills)
        if items:
            blocks.append(_styled_block(content, "专业技能", f"\\ResumeSection{{专业技能}}\n{items}"))
    return "\n\n".join(blocks) or "\\ResumeSection[0pt]{简历内容}\n暂无可导出的已确认内容。"


def _photo_block(avatar_name: str | None) -> str:
    if not avatar_name:
        return ""
    return (
        r"\put(497.127,-24.351){\raisebox{-\height}{\begingroup\setlength{\fboxsep}{0pt}"
        r"\setlength{\fboxrule}{0.70pt}\fcolorbox{ResumeBorder}{white}{"
        rf"\includegraphics[width=68pt,height=84pt,keepaspectratio]{{{avatar_name}}}"
        r"}\endgroup}}"
    )


def render_resume_tex(content: dict[str, Any], user: Any, title: str = "", avatar_name: str | None = None) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    layout = _layout(content)
    body_size = _layout_value(layout.get("fontSize"), 10.5, 8, 16)
    body_leading = body_size * 1.5
    padding = _layout_value(layout.get("padding"), 15, 8, 24)
    phone = _escape_tex(getattr(user, "phone", ""))
    email = _escape_tex(getattr(user, "email", ""))
    contact_parts = []
    if phone:
        contact_parts.append(rf"\ResumeIcon{{\faPhone}}{{\href{{tel:{phone}}}{{{phone}}}}}")
    if email:
        contact_parts.append(rf"\ResumeIcon{{\faEnvelope}}{{\href{{mailto:{email}}}{{{email}}}}}")
    contact = "\\hspace{2.2em}".join(contact_parts)
    role = _escape_tex(content.get("headline") or getattr(user, "target_role", "") or title or "求职简历")
    replacements = {
        "%%GEOMETRY%%": f"\\usepackage[left={padding:.1f}mm,right={padding:.1f}mm,top={padding:.1f}mm,bottom={padding:.1f}mm,headheight=0pt,headsep=0pt,footskip=0pt]{{geometry}}",
        "%%BODY_FONT%%": f"\\fontsize{{{body_size:.1f}pt}}{{{body_leading:.2f}pt}}\\selectfont",
        "%%NAME%%": _escape_tex(getattr(user, "full_name", "") or "未填写姓名"),
        "%%CONTACT%%": contact,
        "%%TARGET_ROLE%%": role,
        "%%PHOTO_BLOCK%%": _photo_block(avatar_name),
        "%%CONTENT%%": _content(content),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def _avatar_source(user: Any) -> Path | None:
    path = getattr(user, "avatar_file_path", None)
    if not path:
        return None
    source = Path(path)
    return source if source.is_file() else None


def build_tex_bundle(content: dict[str, Any], user: Any, title: str = "") -> bytes:
    avatar = _avatar_source(user)
    avatar_name = f"resume-avatar{avatar.suffix.lower()}" if avatar else None
    tex = render_resume_tex(content, user, title, avatar_name)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("resume.tex", tex)
        if avatar and avatar_name:
            archive.write(avatar, avatar_name)
    return output.getvalue()


def compile_resume_pdf(content: dict[str, Any], user: Any, title: str = "") -> bytes:
    if not shutil.which("xelatex"):
        raise RuntimeError("XeLaTeX is not installed on the server")
    avatar = _avatar_source(user)
    avatar_name = f"resume-avatar{avatar.suffix.lower()}" if avatar else None
    tex = render_resume_tex(content, user, title, avatar_name)
    with tempfile.TemporaryDirectory(prefix="career-resume-") as directory:
        workspace = Path(directory)
        tex_path = workspace / "resume.tex"
        tex_path.write_text(tex, encoding="utf-8")
        if avatar and avatar_name:
            shutil.copyfile(avatar, workspace / avatar_name)
        result = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "resume.tex"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=MAX_COMPILE_SECONDS,
            check=False,
        )
        pdf_path = workspace / "resume.pdf"
        if result.returncode != 0 or not pdf_path.is_file():
            details = (result.stdout + result.stderr)[-1200:]
            raise RuntimeError(f"XeLaTeX failed to compile the resume: {details}")
        return pdf_path.read_bytes()

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
FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
PROJECT_FONT_FILES = (
    "simsun.ttc",
    "times.ttf",
    "timesbd.ttf",
    "timesi.ttf",
    "timesbi.ttf",
)
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


def _rich_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"• \1 ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</?(?:ul|ol)[^>]*>", "", text, flags=re.IGNORECASE)
    parts = re.split(r"(<(?:strong|b)>.*?</(?:strong|b)>|<(?:em|i)>.*?</(?:em|i)>)", text, flags=re.IGNORECASE | re.DOTALL)
    rendered: list[str] = []
    for part in parts:
        match = re.fullmatch(r"<(?:strong|b)>(.*?)</(?:strong|b)>", part, flags=re.IGNORECASE | re.DOTALL)
        if match:
            inner = re.sub(r"<br\s*/?>", " ", match.group(1), flags=re.IGNORECASE)
            rendered.append(rf"\textbf{{{_escape_tex(re.sub(r'<[^>]+>', '', inner))}}}")
            continue
        match = re.fullmatch(r"<(?:em|i)>(.*?)</(?:em|i)>", part, flags=re.IGNORECASE | re.DOTALL)
        if match:
            inner = re.sub(r"<br\s*/?>", " ", match.group(1), flags=re.IGNORECASE)
            rendered.append(rf"\textit{{{_escape_tex(re.sub(r'<[^>]+>', '', inner))}}}")
        else:
            plain = re.sub(r"<br\s*/?>", " ", part, flags=re.IGNORECASE)
            rendered.append(_escape_tex(re.sub(r"<[^>]+>", "", plain)))
    return "".join(rendered)


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
    size = _layout_value(style.get("fontSize", layout.get("fontSize", 10.5)), 10.5, 9.5, 16)
    weight = int(_layout_value(style.get("fontWeight", 400), 400, 400, 800))
    color = str(style.get("color") or "#17202a")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        color = "#17202a"
    return size, weight, color[1:]


def _styled_block(content: dict[str, Any], key: str, block: str) -> str:
    size, weight, color = _section_style(content, key)
    leading = size
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
        text = _rich_text(value)
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
        summary = entry.get("summary")
        if summary:
            label = "项目简介" if heading == "项目经历" else "个人职责与成果"
            rendered.append(f"\\textbf{{{label}：}} {_rich_text(summary)}\\par")
        tech_stack = entry.get("tech_stack")
        if isinstance(tech_stack, list):
            tech_stack = "、".join(str(item) for item in tech_stack if str(item).strip())
        tech_stack = _rich_text(tech_stack)
        if tech_stack:
            rendered.append(f"\\textbf{{技术栈：}} {tech_stack}\\par")
        items = _items(entry.get("items") if isinstance(entry.get("items"), list) else [])
        if items:
            label = "技术亮点" if heading == "项目经历" else "核心成果"
            rendered.append(f"\\textbf{{{label}：}}\\par\n" + items)
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
            rendered.append("\\quad ".join(details) + "\\par")
        if extra_details:
            rendered.append(_escape_tex(extra_details) + "\\par")
    if not rendered:
        return ""
    return "\\ResumeSection[0pt]{教育背景}\n" + "\n".join(rendered)


def _content(content: dict[str, Any]) -> str:
    blocks: list[str] = []
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
        return r"\rule{0pt}{84pt}\hspace{68pt}"
    return rf"\includegraphics[width=68pt,height=84pt,keepaspectratio]{{{avatar_name}}}"


def _project_font_config() -> str:
    available = {name: FONT_DIR / name for name in PROJECT_FONT_FILES if (FONT_DIR / name).is_file()}
    config: list[str] = []
    if "times.ttf" in available:
        times_options = ["Path=fonts/", "UprightFont=times.ttf"]
        times_options.extend(
            [
                "BoldFont=timesbd.ttf" if "timesbd.ttf" in available else "",
                "ItalicFont=timesi.ttf" if "timesi.ttf" in available else "",
                "BoldItalicFont=timesbi.ttf" if "timesbi.ttf" in available else "",
            ]
        )
        options = ",\n  ".join(option for option in times_options if option)
        config.append(rf"\setmainfont[{options}]{{times}}")
        config.append(rf"\setsansfont[{options}]{{times}}")
    else:
        config.append(
            r"\IfFontExistsTF{Times New Roman}{\setmainfont{Times New Roman}\setsansfont{Times New Roman}}{\setmainfont{Tinos}\setsansfont{Tinos}}"
        )
    if "simsun.ttc" in available:
        config.append(r"\setCJKmainfont[Path=fonts/,Extension=.ttc]{simsun}")
        config.append(r"\setCJKsansfont[Path=fonts/,Extension=.ttc]{simsun}")
    else:
        config.append(
            r"\IfFontExistsTF{SimSun}{\setCJKmainfont{SimSun}\setCJKsansfont{SimSun}}{\setCJKmainfont{Noto Serif CJK SC}\setCJKsansfont{Noto Serif CJK SC}}"
        )
    return "\n".join(config)


def render_resume_tex(content: dict[str, Any], user: Any, title: str = "", avatar_name: str | None = None) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    layout = _layout(content)
    body_size = _layout_value(layout.get("fontSize"), 10.5, 9.5, 16)
    body_leading = body_size
    section_title_size = _layout_value(layout.get("sectionTitleFontSize"), 12, 11, 18)
    section_title_leading = section_title_size * 1.25
    padding = _layout_value(layout.get("padding"), 15, 8, 24)
    phone = _escape_tex(getattr(user, "phone", ""))
    email = _escape_tex(getattr(user, "email", ""))
    contact_parts = []
    if phone:
        contact_parts.append(rf"\ResumeIcon{{\faPhone}}{{\textbf{{手机：}}\href{{tel:{phone}}}{{{phone}}}}}")
    if email:
        contact_parts.append(rf"\ResumeIcon{{\faEnvelope}}{{\textbf{{邮箱：}}\href{{mailto:{email}}}{{{email}}}}}")
    contact = "\\hspace{2.2em}".join(contact_parts)
    role = _escape_tex(content.get("headline") or getattr(user, "target_role", "") or title or "求职简历")
    replacements = {
        "%%GEOMETRY%%": f"\\usepackage[left={padding:.1f}mm,right={padding:.1f}mm,top={padding:.1f}mm,bottom={padding:.1f}mm,headheight=0pt,headsep=0pt,footskip=0pt]{{geometry}}",
        "%%FONT_CONFIG%%": _project_font_config(),
        "%%BODY_FONT%%": f"\\fontsize{{{body_size:.1f}pt}}{{{body_leading:.2f}pt}}\\selectfont",
        "%%SECTION_TITLE_FONT%%": f"\\fontsize{{{section_title_size:.1f}pt}}{{{section_title_leading:.2f}pt}}\\selectfont",
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
        for font_name in PROJECT_FONT_FILES:
            font_path = FONT_DIR / font_name
            if font_path.is_file():
                archive.write(font_path, f"fonts/{font_name}")
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
        font_workspace = workspace / "fonts"
        for font_name in PROJECT_FONT_FILES:
            font_path = FONT_DIR / font_name
            if font_path.is_file():
                font_workspace.mkdir(exist_ok=True)
                shutil.copyfile(font_path, font_workspace / font_name)
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

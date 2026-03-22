#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py - Newsletter HTML Builder
Converts Notion markdown export to a static HTML newsletter website.
한국교육학회 제주지회 뉴스레터 빌더

Usage: python build.py [--src /path/to/export] [--out /path/to/output]
"""

import os
import re
import shutil
import hashlib
from pathlib import Path
from urllib.parse import unquote
import argparse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_SRC = "C:/Users/user/AppData/Local/Temp/newsletter_export"
DEFAULT_OUT = str(Path(__file__).parent)

NEWSLETTER_TITLE = "한국교육학회 제주지회 뉴스레터"
NEWSLETTER_SUBTITLE = "재창간호"
PUBLICATION_DATE = "2025년 10월 15일"
SINCE = "Since 1993"
PUBLISHER = "한국교육학회 제주지회"
PUBLISHER_NAME = "이인회"
EDITORS = "양은별, 황현철"
ADDRESS = "제주대학교 아라캠퍼스 사범대학 2호관 1312호"
CAFE_URL = "https://cafe.naver.com/kerajeju"
FEEDBACK_EMAIL = "e.yang@jejunu.ac.kr"
FEEDBACK_NAME = "제주대학교 양은별"
DONATION_ACCOUNT = "(농협) 302-2028-2520-51  이인회(제주지회)"

# ---------------------------------------------------------------------------
# Image handling
# ---------------------------------------------------------------------------
# Maps: source_abs_path (str) → local_relative_path (str, e.g. "images/xxx.png")
_image_registry = {}


def register_image(md_file_path, url_encoded_path):
    """Register an image from a Notion URL-encoded path.
    md_file_path: Path object of the .md file
    url_encoded_path: the raw image path from markdown (may be URL-encoded)
    Returns: local relative path string (e.g. 'images/abc123_name.png')
    """
    if url_encoded_path.startswith('http'):
        return url_encoded_path  # external URL, keep as-is

    decoded = unquote(url_encoded_path)
    src_dir = md_file_path.parent
    # Resolve relative paths (handles .. etc.)
    try:
        abs_path = str(Path(str(src_dir / decoded)).resolve())
    except Exception:
        abs_path = str(src_dir / decoded)

    if abs_path in _image_registry:
        return _image_registry[abs_path]

    # Create a stable filename: hash prefix + sanitized original name
    orig_name = Path(decoded).name
    h = hashlib.md5(abs_path.encode('utf-8')).hexdigest()[:8]
    # Sanitize: replace spaces and special chars
    safe_name = re.sub(r'[^\w._-]', '_', orig_name)
    local_name = f"{h}_{safe_name}"
    local_rel = f"images/{local_name}"

    _image_registry[abs_path] = local_rel
    return local_rel


def copy_all_images(out_dir):
    """Copy all registered images from source to out_dir/images/."""
    img_dir = Path(out_dir) / 'images'
    img_dir.mkdir(exist_ok=True)
    copied = 0
    missing = 0
    for abs_src, local_rel in _image_registry.items():
        if abs_src.startswith('http'):
            continue
        dest = Path(out_dir) / local_rel
        if os.path.exists(abs_src):
            try:
                shutil.copy2(abs_src, str(dest))
                copied += 1
            except Exception as e:
                print(f"  Warning copying {Path(abs_src).name}: {e}")
        else:
            missing += 1
    print(f"  Images: {copied} copied, {missing} source not found")


# ---------------------------------------------------------------------------
# Markdown → HTML helpers
# ---------------------------------------------------------------------------

def slugify(text):
    """Create an anchor-safe ID from text."""
    text = re.sub(r'[^\w가-힣]', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    return text[:60] or 'section'


def escape_html(text):
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


def apply_inline(text, md_file):
    """Apply inline markdown: bold, italic, code, links, images."""
    # Process HTML img tags FIRST (before markdown img conversion, to avoid double-processing)
    # These appear in Notion asides: <img src="%EC%..." alt="..." width="40px" />
    def html_img_replace(m):
        src = m.group(1)
        attrs = m.group(2)
        if src.startswith('http') or src.startswith('images/'):
            return m.group(0)  # already processed or external — leave unchanged
        local = register_image(md_file, src)
        return f'<img src="{local}" {attrs}>'
    text = re.sub(r'<img\s+src="([^"]+)"([^>]*?)/?>', html_img_replace, text)

    # Markdown images: ![alt](path)
    # Note: URL paths may contain literal ( and ) characters (e.g. Notion date directories)
    # Use a regex that allows balanced or escaped parens in the URL
    def img_replace(m):
        alt = m.group(1)
        path = m.group(2)
        local = register_image(md_file, path)
        return f'<img src="{local}" alt="{escape_html(alt)}" loading="lazy">'
    # Pattern: allow balanced () inside URL (handles Notion paths like (2025 1 24 )/image.png)
    text = re.sub(r'!\[([^\]]*)\]\(((?:[^)(]|\([^)]*\))+)\)', img_replace, text)

    # Links: [text](url) — skip CSV links
    def link_replace(m):
        link_text = m.group(1)
        url = m.group(2)
        if '.csv' in url:
            return ''  # internal Notion database link
        return f'<a href="{url}" target="_blank" rel="noopener">{link_text}</a>'
    # Allow balanced () inside URL
    text = re.sub(r'\[([^\]]+)\]\(((?:[^)(]|\([^)]*\))+)\)', link_replace, text)

    # Bold+italic, bold, italic, code
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Remove any remaining stray ** (multi-line bold that couldn't be matched)
    text = text.replace('**', '')
    return text


def parse_table(lines, start_idx):
    """Parse a markdown table. Returns (html, next_index)."""
    rows = []
    i = start_idx
    while i < len(lines):
        line = lines[i]
        if '|' not in line:
            break
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        rows.append(cells)
        i += 1
    if not rows:
        return '', start_idx + 1

    # Remove separator row
    real_rows = []
    for row in rows:
        if not all(re.match(r'^[-:]+$', c.replace(' ', '')) for c in row if c):
            real_rows.append(row)

    if not real_rows:
        return '', i

    html = '<div class="table-wrap"><table>\n'
    html += '<thead><tr>' + ''.join(f'<th>{c}</th>' for c in real_rows[0]) + '</tr></thead>\n'
    html += '<tbody>\n'
    for row in real_rows[1:]:
        html += '<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>\n'
    html += '</tbody></table></div>\n'
    return html, i


def convert_aside_content(content, md_file):
    """Convert the raw content inside <aside>...</aside> to HTML spans."""
    lines = content.strip().split('\n')
    parts = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if re.match(r'^-{3,}$', s):
            parts.append('<hr>')
            continue
        # Apply inline transformations
        s = apply_inline(s, md_file)
        parts.append(f'<span>{s}</span>')
    return '\n'.join(parts)


def md_to_html(md_text, md_file):
    """Convert markdown text to HTML fragment.
    md_file: Path object of the source .md file (for image resolution).
    """
    lines = md_text.split('\n')
    out = []
    i = 0

    # State
    in_aside = False
    aside_buf = []
    in_list_ul = False
    in_list_ol = False
    list_buf = []
    in_blockquote = False
    bq_buf = []

    def flush_ul():
        nonlocal in_list_ul, list_buf
        if not in_list_ul:
            return
        out.append('<ul>\n' + ''.join(f'<li>{apply_inline(t, md_file)}</li>\n' for t in list_buf) + '</ul>\n')
        in_list_ul = False
        list_buf = []

    def flush_ol():
        nonlocal in_list_ol, list_buf
        if not in_list_ol:
            return
        out.append('<ol>\n' + ''.join(f'<li>{apply_inline(t, md_file)}</li>\n' for t in list_buf) + '</ol>\n')
        in_list_ol = False
        list_buf = []

    def flush_bq():
        nonlocal in_blockquote, bq_buf
        if not in_blockquote:
            return
        content = ' '.join(bq_buf)
        out.append(f'<blockquote>{apply_inline(content, md_file)}</blockquote>\n')
        in_blockquote = False
        bq_buf = []

    def flush_all():
        flush_ul()
        flush_ol()
        flush_bq()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- ASIDE blocks ---
        if stripped == '<aside>':
            flush_all()
            in_aside = True
            aside_buf = []
            i += 1
            continue

        if in_aside:
            if stripped == '</aside>':
                aside_html = convert_aside_content('\n'.join(aside_buf), md_file)
                out.append(f'<div class="aside-block">{aside_html}</div>\n')
                in_aside = False
                aside_buf = []
            else:
                aside_buf.append(line)
            i += 1
            continue

        # --- Blockquote ---
        if stripped.startswith('> ') or stripped == '>':
            flush_ul()
            flush_ol()
            content = stripped[2:] if stripped.startswith('> ') else ''
            if not in_blockquote:
                in_blockquote = True
                bq_buf = [content]
            else:
                bq_buf.append(content)
            i += 1
            continue
        elif in_blockquote and stripped:
            # continuation lines of blockquote without >
            pass
        else:
            flush_bq()

        # --- Horizontal rule ---
        if re.match(r'^[-*_]{3,}$', stripped):
            flush_all()
            out.append('<hr>\n')
            i += 1
            continue

        # --- Headings ---
        m = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if m:
            flush_all()
            level = min(len(m.group(1)), 4)  # cap at h4
            text = m.group(2)
            # Strip bold markers from heading text
            text_clean = re.sub(r'\*+(.+?)\*+', r'\1', text).strip()
            slug = slugify(text_clean)
            out.append(f'<h{level} id="{slug}">{escape_html(text_clean)}</h{level}>\n')
            i += 1
            continue

        # --- Table ---
        if stripped.startswith('|') and '|' in stripped:
            flush_all()
            tbl_html, i = parse_table(lines, i)
            out.append(tbl_html)
            continue

        # --- Unordered list ---
        m = re.match(r'^[-*+]\s+(.+)$', stripped)
        if m:
            flush_ol()
            flush_bq()
            in_list_ul = True
            list_buf.append(m.group(1))
            i += 1
            continue

        # --- Ordered list ---
        m = re.match(r'^\d+\.\s+(.+)$', stripped)
        if m:
            flush_ul()
            flush_bq()
            in_list_ol = True
            list_buf.append(m.group(1))
            i += 1
            continue

        # End of list if non-list line
        if stripped and not re.match(r'^[-*+\d]', stripped):
            flush_ul()
            flush_ol()

        # --- Empty line ---
        if not stripped:
            flush_ul()
            flush_ol()
            i += 1
            continue

        # --- Skip CSV/database links ---
        if re.match(r'^\[.+\]\(.+\.csv\)$', stripped):
            i += 1
            continue

        # --- Regular paragraph ---
        processed = apply_inline(stripped, md_file)
        # Skip empty after processing
        if processed.strip():
            out.append(f'<p>{processed}</p>\n')
        i += 1

    flush_all()
    return ''.join(out)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_newsletter_subdir(src_root):
    """Find the main newsletter content directory."""
    src_root = Path(src_root)
    # Walk looking for a dir that contains 주론, 시론, etc.
    for d in src_root.rglob('*'):
        if not d.is_dir():
            continue
        name = d.name
        if '제주지회 뉴스레터' in name and not name.endswith('.csv'):
            # Check if it actually has MD files
            mds = list(d.glob('*.md'))
            if mds:
                return d
    raise FileNotFoundError(f"Cannot find newsletter content dir in {src_root}")


def find_root_md(src_root):
    """Find the root-level MD file (발간사)."""
    for f in Path(src_root).glob('*.md'):
        return f
    return None


def collect_md_files(subdir):
    """Collect all .md files under subdir."""
    return sorted(Path(subdir).rglob('*.md'))


def find_file_by_key(all_files, key):
    """Find a file whose name contains the key string (case-sensitive Korean)."""
    # Exact substring match
    for f in all_files:
        if key in f.name:
            return f
    # Try matching first two words
    words = key.split()
    if len(words) >= 2:
        for f in all_files:
            if words[0] in f.name and words[1] in f.name:
                return f
    if len(words) >= 1:
        for f in all_files:
            if words[0] in f.name:
                return f
    return None


def read_md(path):
    with open(str(path), encoding='utf-8', errors='replace') as f:
        return f.read()


# ---------------------------------------------------------------------------
# Section structure
# ---------------------------------------------------------------------------

SECTIONS = [
    {
        'id': 'juron',
        'title': '제주교육의 정체성 구현과 제주지회의 활성화',
        'nav_title': '주론',
        'subtitle': '',
        'icon': '',
        'color': '#1a5c35',
        'file_key': '주론 237',
        'subsections': []
    },
    {
        'id': 'siron',
        'title': '제주도 교육 특별자치, 이제 어드레 가멘?',
        'nav_title': '시론',
        'subtitle': '',
        'icon': '',
        'color': '#1a5c35',
        'file_key': '시론 237',
        'subsections': []
    },
    {
        'id': 'activities',
        'title': '제주지회 활동 소개',
        'subtitle': '',
        'icon': '',
        'color': '#2d6a4f',
        'file_key': '',
        'subsections': [
            {'title': '구성원 소개', 'file_key': '제주지회 활동 소개 237'},
            {'title': '창립 58주년 기념 강연 (2025.1.24.)', 'file_key': '창립 58주년 기념 강연'},
            {'title': '원도심마을탐방 (2025.4.26.)', 'file_key': '원도심마을탐방'},
            {'title': '2025 임원회의 (2025.9.12.)', 'file_key': '2025 임원회의'},
            {'title': '— 향후 활동 계획 —', 'file_key': '', 'is_divider': True},
            {'title': '제주교육학 제4차 공동학술대회', 'file_key': '제주교육학 제 4차 공동학술대회'},
            {'title': '2026년 창립 59주년 학술행사', 'file_key': '2026년 창립 59주년'},
        ]
    },
    {
        'id': 'member',
        'title': '회원 동정',
        'subtitle': '',
        'icon': '',
        'color': '#40916c',
        'file_key': '',
        'subsections': [
            {'title': '연구비 수주', 'file_key': '연구비 수주'},
            {'title': '회원 신간 안내', 'file_key': '회원 신간 안내'},
            {'title': '회원 소식', 'file_key': '회원 소식 237'},
        ]
    },
    {
        'id': 'jeju-news',
        'title': '제주교육소식',
        'subtitle': '',
        'icon': '',
        'color': '#52b788',
        'file_key': '',
        'subsections': [
            {'title': '생생 수업 나눔', 'file_key': '생생 수업 나눔'},
            {'title': '교수님의 연구실', 'file_key': '교수님의 연구실'},
            {'title': '스마트 교실 비밀병기', 'file_key': '스마트 교실 비밀병기'},
            {'title': '제주교육 나침반', 'file_key': '제주교육 나침반'},
            {'title': '동백꽃 편지', 'file_key': '동백꽃 편지'},
            {'title': '이어가는 이야기', 'file_key': '이어가는 이야기'},
        ]
    },
    {
        'id': 'campus',
        'title': '캠퍼스 네트워크',
        'subtitle': '',
        'icon': '',
        'color': '#74c69d',
        'file_key': '',
        'subsections': [
            {'title': '제주한라대학교', 'file_key': '제주한라대학교'},
            {'title': '제주국제대학교', 'file_key': '제주국제대학교'},
            {'title': '— 제주대학교 아라캠퍼스 —', 'file_key': '', 'is_divider': True},
            {'title': '마을과 함께 가꾸는 교육의 터전', 'file_key': '마을과 함께 가꾸는 교육의 터전'},
            {'title': '2025 프론티어방 하계 워크숍', 'file_key': '2025 프론티어방 하계 워크숍'},
            {'title': '— 제주대학교 사라캠퍼스 —', 'file_key': '', 'is_divider': True},
            {'title': '2025 유럽 선진 숲 교육기관 연수', 'file_key': '2025 유럽 선진 숲 교육기관 연수'},
            {'title': '신입생 소개 — 이선아', 'file_key': '신입생 소개 26cf7f2dc41f80df'},
            {'title': '신입생 소개 — 김신회', 'file_key': '신입생 소개 28bf7f2dc41f80c5'},
        ]
    },
]


# ---------------------------------------------------------------------------
# HTML section builders
# ---------------------------------------------------------------------------

def strip_h1(md):
    """Remove the first H1 heading from markdown."""
    return re.sub(r'^#\s+.+\n?', '', md, count=1)


def extract_metadata(md):
    """Extract metadata lines (제목:, 날짜:, 연구실:, 장소:) and return (metadata_dict, cleaned_md)."""
    meta = {}
    lines = md.split('\n')
    clean = []
    for line in lines:
        m = re.match(r'^(제목|날짜|장소|연구실)\s*:\s*(.+)$', line.strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()
        else:
            clean.append(line)
    return meta, '\n'.join(clean)


def build_section_html(section, all_files):
    sid = section['id']
    title = section['title']
    subtitle = section.get('subtitle', '')
    icon = section.get('icon', '')
    color = section.get('color', '#2d7d46')

    # Main content
    main_content = ''
    if section.get('file_key'):
        main_file = find_file_by_key(all_files, section['file_key'])
        if main_file:
            md = strip_h1(read_md(main_file))
            # Remove CSV links (Notion database embeds)
            md = re.sub(r'\[.+?\]\(.+?\.csv\)\n?', '', md)
            main_content = md_to_html(md, main_file)

    # Subsections
    subs_html = ''
    if section.get('subsections'):
        sub_parts = []
        for sub in section['subsections']:
            sub_title = sub['title']
            sub_key = sub.get('file_key', '')
            # Divider (group header)
            if sub.get('is_divider'):
                sub_parts.append(f'<div class="subsection-divider"><strong>{escape_html(sub_title)}</strong></div>')
                continue
            sub_file = find_file_by_key(all_files, sub_key) if sub_key else None
            if not sub_file:
                if sub_key:
                    print(f"  Warning: not found: '{sub_key}'")
                continue
            sub_md = read_md(sub_file)
            sub_md = strip_h1(sub_md)
            meta, sub_md = extract_metadata(sub_md)
            sub_id = slugify(sub_title)
            # Build subtitle from metadata
            meta_parts = []
            if '제목' in meta:
                meta_parts.append(meta['제목'])
            elif '날짜' in meta:
                meta_parts.append(meta['날짜'])
            elif '연구실' in meta:
                meta_parts.append(meta['연구실'])
            meta_label = ' · '.join(meta_parts)
            sub_html = md_to_html(sub_md, sub_file)
            sub_parts.append(f'''
<div class="subsection" id="{sub_id}">
  <details>
    <summary>
      <span class="sub-title">{escape_html(sub_title)}</span>
      {('<span class="sub-subtitle">' + escape_html(meta_label) + '</span>') if meta_label else ''}
    </summary>
    <div class="sub-content">{sub_html}</div>
  </details>
</div>''')
        if sub_parts:
            subs_html = '<div class="subsections">' + '\n'.join(sub_parts) + '</div>'

    return f'''
<section id="{sid}" class="newsletter-section">
  <div class="section-header" style="border-left-color:{color}">
    <span class="section-icon">{icon}</span>
    <div>
      <h2 class="section-title">{escape_html(title)}</h2>
      {('<p class="section-subtitle">' + escape_html(subtitle) + '</p>') if subtitle else ''}
    </div>
  </div>
  <div class="section-content">
    {main_content}
    {subs_html}
  </div>
</section>
'''


def build_intro_html(root_md_path):
    if not root_md_path or not os.path.exists(str(root_md_path)):
        return ''
    md = read_md(root_md_path)
    md = strip_h1(md)
    # Remove CSV/database links
    md = re.sub(r'\[.+?\]\(.+?\.csv\)\n?', '', md)
    # Remove Notion navigation aside (cursor-click)
    md = re.sub(r'<aside>.*?cursor-click.*?</aside>', '', md, flags=re.DOTALL)
    content = md_to_html(md, root_md_path)
    return f'''
<section id="intro" class="newsletter-section intro-section">
  <div class="section-header" style="border-left-color:#1a5c35">
    <span class="section-icon"></span>
    <div>
      <h2 class="section-title">발간사</h2>
    </div>
  </div>
  <div class="section-content">
    {content}
  </div>
</section>
'''


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """
/* ============================================================
   Newsletter CSS — 한국교육학회 제주지회
   ============================================================ */

*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

:root {
    --green-dark:   #1a5c35;
    --green-mid:    #2d7d46;
    --green-light:  #52b788;
    --green-pale:   #d8f3dc;
    --green-faint:  #f0faf3;
    --white:        #ffffff;
    --gray-light:   #f8f9fa;
    --gray-mid:     #e9ecef;
    --gray-text:    #495057;
    --black:        #212529;
    --font-main:    'Noto Serif KR', 'NanumMyeongjo', Georgia, serif;
    --font-ui:      'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    --shadow-sm:    0 1px 3px rgba(0,0,0,.08);
    --shadow-md:    0 4px 12px rgba(0,0,0,.12);
    --radius:       8px;
    --max-width:    900px;
}

html { scroll-behavior: smooth; font-size: 16px; }

body {
    font-family: var(--font-main);
    color: var(--black);
    background: var(--gray-light);
    line-height: 1.8;
}

/* NAV */
nav.site-nav {
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--green-dark);
    box-shadow: var(--shadow-md);
}
.nav-inner {
    max-width: var(--max-width);
    margin: 0 auto;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1.5rem;
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}
.nav-brand {
    color: var(--white);
    font-family: var(--font-ui);
    font-size: 0.8rem;
    font-weight: 700;
    white-space: nowrap;
    text-decoration: none;
    flex-shrink: 0;
}
.toc-list {
    display: flex;
    list-style: none;
    gap: 0.15rem;
    flex-wrap: nowrap;
    flex-shrink: 0;
}
.toc-list a {
    color: #b7e4c7;
    text-decoration: none;
    font-family: var(--font-ui);
    font-size: 0.78rem;
    padding: 0.2rem 0.55rem;
    border-radius: 4px;
    transition: background 0.2s, color 0.2s;
    white-space: nowrap;
}
.toc-list a:hover, .toc-list a.active {
    background: rgba(255,255,255,0.2);
    color: var(--white);
}
.toc-list a.active {
    background: rgba(255,255,255,0.25);
    font-weight: 700;
}

/* MASTHEAD */
.masthead {
    background: linear-gradient(135deg, var(--green-dark) 0%, var(--green-mid) 60%, var(--green-light) 100%);
    color: var(--white);
    padding: 3rem 1.5rem 2rem;
    text-align: center;
}
.masthead-inner {
    max-width: var(--max-width);
    margin: 0 auto;
}
.masthead-badge {
    display: inline-flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.5rem 0.75rem;
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.3);
    border-radius: 20px;
    padding: 0.35rem 1rem;
    font-family: var(--font-ui);
    font-size: 0.85rem;
    margin-bottom: 1.5rem;
}
.masthead-badge .sep { opacity: 0.4; }
.masthead h1 {
    font-size: clamp(1.5rem, 5vw, 2.5rem);
    font-weight: 900;
    letter-spacing: -0.02em;
    margin-bottom: 0.5rem;
    text-shadow: 0 2px 8px rgba(0,0,0,0.2);
}
.masthead-sub {
    font-family: var(--font-ui);
    font-size: 0.9rem;
    opacity: 0.85;
    margin-bottom: 1.5rem;
}
.masthead-hero-img {
    margin: 0 auto;
    max-width: 720px;
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow: var(--shadow-md);
}
.masthead-hero-img img {
    width: 100%;
    height: auto;
    display: block;
}

/* LAYOUT */
main {
    max-width: var(--max-width);
    margin: 0 auto;
    padding: 2rem 1.5rem;
}

/* SECTIONS */
.newsletter-section {
    background: var(--white);
    border-radius: var(--radius);
    box-shadow: var(--shadow-sm);
    margin-bottom: 2.5rem;
    overflow: hidden;
}
.section-header {
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    padding: 1.5rem 1.75rem 1rem;
    border-left: 5px solid var(--green-mid);
    background: var(--green-faint);
}
.section-icon {
    font-size: 1.4rem;
    flex-shrink: 0;
    margin-top: 0.1em;
}
.section-title {
    font-size: 1.4rem;
    font-weight: 800;
    color: var(--green-dark);
    font-family: var(--font-ui);
    line-height: 1.3;
}
.section-subtitle {
    font-family: var(--font-ui);
    font-size: 0.88rem;
    color: #40916c;
    margin-top: 0.25rem;
    line-height: 1.4;
}
.section-content {
    padding: 1.5rem 1.75rem;
    overflow-wrap: break-word;
    word-break: keep-all;
}

/* TYPOGRAPHY */
.section-content h1,
.section-content h2,
.section-content h3,
.section-content h4 {
    font-family: var(--font-ui);
    color: var(--green-dark);
    margin: 1.5rem 0 0.6rem;
    line-height: 1.4;
}
.section-content h1 { font-size: 1.25rem; border-bottom: 2px solid var(--green-pale); padding-bottom: 0.3rem; }
.section-content h2 { font-size: 1.1rem; }
.section-content h3 { font-size: 1rem; }
.section-content h4 { font-size: 0.95rem; color: var(--green-mid); }

.section-content p {
    margin-bottom: 1rem;
    line-height: 1.9;
    color: #333;
}
.section-content strong { color: var(--green-dark); font-weight: 700; }
.section-content em { font-style: italic; }
.section-content code {
    background: var(--green-pale);
    color: var(--green-dark);
    padding: 0.1em 0.4em;
    border-radius: 3px;
    font-family: var(--font-ui);
    font-size: 0.85em;
}
.section-content hr {
    border: none;
    border-top: 1px solid var(--gray-mid);
    margin: 1.5rem 0;
}
.section-content blockquote {
    border-left: 3px solid var(--green-light);
    padding: 0.75rem 1rem;
    margin: 1rem 0;
    background: var(--green-faint);
    border-radius: 0 var(--radius) var(--radius) 0;
    font-style: italic;
    color: var(--gray-text);
}
.section-content ul, .section-content ol {
    padding-left: 1.5rem;
    margin-bottom: 1rem;
}
.section-content li { margin-bottom: 0.3rem; }
.section-content a {
    color: var(--green-mid);
    text-decoration: underline;
    text-decoration-color: var(--green-pale);
    transition: color 0.2s;
}
.section-content a:hover { color: var(--green-dark); }

/* IMAGES */
.section-content img {
    max-width: 100%;
    height: auto;
    border-radius: var(--radius);
    display: block;
    margin: 1.25rem auto;
    box-shadow: var(--shadow-sm);
}
.section-content img[alt*="교수"],
.section-content img[alt*="선생님"],
.section-content img[alt*="사진"],
.section-content img[alt*="증명"] {
    max-width: 160px;
    border-radius: 50%;
    object-fit: cover;
    aspect-ratio: 1;
    object-position: top;
}

/* ASIDE BLOCKS */
.aside-block {
    background: var(--green-faint);
    border-left: 3px solid var(--green-light);
    border-radius: 0 var(--radius) var(--radius) 0;
    padding: 1rem 1.25rem;
    margin: 1rem 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
}
.aside-block span {
    display: block;
    font-size: 0.93rem;
    color: var(--gray-text);
    line-height: 1.7;
}
.aside-block strong { color: var(--green-dark); }
.aside-block code {
    background: var(--green-pale);
    color: var(--green-dark);
    padding: 0.1em 0.35em;
    border-radius: 3px;
    font-size: 0.85em;
    font-family: var(--font-ui);
}
.aside-block hr { border: none; border-top: 1px solid var(--gray-mid); margin: 0.25rem 0; }
.aside-block img {
    max-width: 120px;
    border-radius: 50%;
    display: block;
    margin: 0.25rem auto;
    box-shadow: none;
}

/* TABLES */
.table-wrap {
    overflow-x: auto;
    margin: 1.25rem 0;
    border-radius: var(--radius);
    box-shadow: var(--shadow-sm);
}
table {
    border-collapse: collapse;
    width: 100%;
    font-family: var(--font-ui);
    font-size: 0.88rem;
}
th {
    background: var(--green-dark);
    color: var(--white);
    padding: 0.65rem 0.9rem;
    text-align: left;
    font-weight: 600;
}
td {
    padding: 0.55rem 0.9rem;
    border-bottom: 1px solid var(--gray-mid);
    vertical-align: top;
    line-height: 1.6;
    word-break: keep-all;
    overflow-wrap: break-word;
}
tr:nth-child(even) td { background: var(--green-faint); }
tr:hover td { background: #e9f5ec; }

/* SUBSECTIONS */
.subsections { margin-top: 1.5rem; border-top: 1px solid var(--gray-mid); padding-top: 1rem; }
.subsection-divider {
    padding: 0.8rem 0 0.3rem;
    font-family: var(--font-ui);
    font-size: 0.9rem;
    color: var(--green-dark);
    border-top: 1px solid var(--gray-mid);
    margin-top: 0.5rem;
}
.subsection {
    border: 1px solid var(--gray-mid);
    border-radius: var(--radius);
    margin-bottom: 0.75rem;
    overflow: hidden;
    transition: box-shadow 0.2s;
}
.subsection:hover { box-shadow: var(--shadow-sm); }
details > summary {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.85rem 1.25rem;
    cursor: pointer;
    background: var(--green-faint);
    font-family: var(--font-ui);
    user-select: none;
    border-left: 3px solid var(--green-light);
    transition: background 0.2s;
    list-style: none;
}
details > summary::-webkit-details-marker { display: none; }
details > summary::before {
    content: '▶';
    color: var(--green-mid);
    font-size: 0.65rem;
    transition: transform 0.2s;
    flex-shrink: 0;
}
details[open] > summary { border-left-color: var(--green-dark); }
details[open] > summary::before { transform: rotate(90deg); }
details > summary:hover { background: var(--green-pale); }
.sub-title {
    font-weight: 700;
    color: var(--green-dark);
    font-size: 0.97rem;
}
.sub-subtitle {
    color: var(--gray-text);
    font-size: 0.82rem;
    font-weight: 400;
    flex-shrink: 0;
}
.sub-content {
    padding: 1.5rem;
    border-top: 1px solid var(--gray-mid);
    background: var(--white);
}

/* FOOTER */
footer {
    background: var(--green-dark);
    color: rgba(255,255,255,0.85);
    padding: 2.5rem 1.5rem 2rem;
    text-align: center;
    font-family: var(--font-ui);
    font-size: 0.85rem;
}
.footer-inner { max-width: var(--max-width); margin: 0 auto; }
.footer-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem 1.5rem;
    text-align: left;
    margin-bottom: 1.5rem;
}
.footer-item label {
    display: block;
    color: var(--green-pale);
    font-size: 0.72rem;
    font-weight: 700;
    margin-bottom: 0.2rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.footer-item span, .footer-item a {
    color: rgba(255,255,255,0.85);
    text-decoration: none;
    line-height: 1.6;
}
.footer-item a:hover { color: var(--green-pale); }
.footer-divider { border: none; border-top: 1px solid rgba(255,255,255,0.15); margin: 1.25rem 0; }
.footer-copy { font-size: 0.78rem; opacity: 0.55; }
.feedback-box {
    background: rgba(255,255,255,0.07);
    border-radius: var(--radius);
    padding: 1rem 1.25rem;
    margin: 0 0 1rem;
    font-size: 0.85rem;
    line-height: 1.8;
    text-align: left;
}
.feedback-box a { color: var(--green-pale); }
.donation-box { font-size: 0.8rem; opacity: 0.7; margin-bottom: 0.5rem; }

/* BACK TO TOP */
.back-top {
    position: fixed;
    bottom: 1.5rem;
    right: 1.5rem;
    background: var(--green-mid);
    color: white;
    border-radius: 50%;
    width: 44px;
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
    text-decoration: none;
    font-size: 1.1rem;
    box-shadow: var(--shadow-md);
    transition: background 0.2s, transform 0.2s;
    opacity: 0.88;
    z-index: 50;
}
.back-top:hover { background: var(--green-dark); transform: translateY(-2px); opacity: 1; }

/* RESPONSIVE */
@media (max-width: 640px) {
    .nav-inner { padding: 0.4rem 0.8rem; gap: 0.3rem; }
    .nav-brand { font-size: 0.7rem; }
    .toc-list { gap: 0.1rem; }
    .toc-list a { font-size: 0.68rem; padding: 0.15rem 0.35rem; }
    main { padding: 1rem; }
    .section-header { padding: 1rem 1.25rem 0.75rem; }
    .section-content { padding: 1rem 1.25rem; }
    .sub-content { padding: 1rem; }
    .masthead { padding: 2rem 1rem 1.5rem; }
    .footer-grid { grid-template-columns: 1fr 1fr; }
}

@media print {
    nav.site-nav, .back-top { display: none; }
    .newsletter-section { box-shadow: none; border: 1px solid #ccc; page-break-inside: avoid; }
    details { display: block !important; }
    details > summary { display: none; }
    .sub-content { display: block !important; padding: 1rem 0; }
}
"""

# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------
INLINE_JS = """
// Tab-based navigation: show only selected section
function showSection(id) {
  // Hide all sections and intro
  document.querySelectorAll('.newsletter-section, .intro-section').forEach(s => {
    s.style.display = 'none';
  });
  // Show selected
  if (id === 'intro') {
    document.querySelectorAll('.intro-section').forEach(s => s.style.display = 'block');
  } else {
    const el = document.getElementById(id);
    if (el) el.style.display = 'block';
  }
  // Update active nav
  document.querySelectorAll('.toc-list a').forEach(a => a.classList.remove('active'));
  const activeLink = document.querySelector('.toc-list a[data-section="' + id + '"]');
  if (activeLink) activeLink.classList.add('active');
  // Scroll to top
  window.scrollTo({ top: 0 });
  // Open first subsection
  const section = document.getElementById(id);
  if (section) {
    const firstDetails = section.querySelector('.subsection:first-child details');
    if (firstDetails) firstDetails.setAttribute('open', '');
  }
}

// Nav click handlers
document.querySelectorAll('.toc-list a').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    const sectionId = a.getAttribute('data-section');
    if (sectionId) showSection(sectionId);
  });
});

// Show intro by default
showSection('intro');
"""


# ---------------------------------------------------------------------------
# Full HTML template
# ---------------------------------------------------------------------------

def build_html(toc_html, intro_html, sections_html, hero_img_src):
    hero = ''
    if hero_img_src:
        hero = f'<div class="masthead-hero-img"><img src="{hero_img_src}" alt="뉴스레터 헤더 이미지"></div>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{NEWSLETTER_TITLE} {NEWSLETTER_SUBTITLE} — {PUBLICATION_DATE}">
  <title>{NEWSLETTER_TITLE} — {NEWSLETTER_SUBTITLE}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;900&family=Noto+Sans+KR:wght@400;600;700&display=swap" rel="stylesheet">
  <style>{CSS}</style>
</head>
<body>

<!-- NAVIGATION -->
<nav class="site-nav" role="navigation" aria-label="목차">
  <div class="nav-inner">
    <a class="nav-brand" href="#" onclick="event.preventDefault(); showSection('intro');">{NEWSLETTER_TITLE}</a>
    {toc_html}
  </div>
</nav>

<!-- MASTHEAD -->
<header class="masthead" role="banner">
  <div class="masthead-inner">
    <h1>{NEWSLETTER_TITLE}</h1>
    {hero}
  </div>
</header>

<!-- CONTENT -->
<main>
  {intro_html}
  {sections_html}
</main>

<!-- FOOTER -->
<footer>
  <div class="footer-inner">
    <div class="footer-grid">
      <div class="footer-item">
        <label>발행처</label>
        <span>{PUBLISHER}</span>
      </div>
      <div class="footer-item">
        <label>발행인</label>
        <span>{PUBLISHER_NAME}</span>
      </div>
      <div class="footer-item">
        <label>편집위원</label>
        <span>{EDITORS}</span>
      </div>
      <div class="footer-item">
        <label>주소</label>
        <span>{ADDRESS}</span>
      </div>
      <div class="footer-item">
        <label>카페</label>
        <a href="{CAFE_URL}" target="_blank" rel="noopener">한국교육학회 제주지회 카페 →</a>
      </div>
    </div>
    <hr class="footer-divider">
    <div class="feedback-box">
      이번 뉴스레터 어떠셨나요? 여러분의 생각과 의견을 기다립니다.<br>
      소중한 의견을 메일로 보내주시면 다음 호에 적극 반영하겠습니다.<br>
      <a href="mailto:{FEEDBACK_EMAIL}">{FEEDBACK_NAME} ✉ {FEEDBACK_EMAIL}</a>
    </div>
    <div class="donation-box">뉴스레터 후원: {DONATION_ACCOUNT}</div>
    <hr class="footer-divider">
    <p class="footer-copy">&copy; 2025 {PUBLISHER}. All rights reserved.</p>
  </div>
</footer>

<a href="#" class="back-top" aria-label="맨 위로">↑</a>

<script>{INLINE_JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# TOC
# ---------------------------------------------------------------------------

def build_toc():
    items = []
    for sec in SECTIONS:
        nav_label = sec.get('nav_title', sec['title'])
        items.append(f'<li><a href="#" data-section="{sec["id"]}">{nav_label}</a></li>')
    return '<ul class="toc-list">' + ''.join(items) + '</ul>'


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build(src_root, out_dir):
    print(f"Building newsletter...")
    print(f"  Source: {src_root}")
    print(f"  Output: {out_dir}")

    # Clear image registry for clean run
    global _image_registry
    _image_registry = {}

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / 'images').mkdir(exist_ok=True)

    # Find source files
    root_md = find_root_md(src_root)
    print(f"  Root MD: {root_md.name if root_md else 'not found'}")

    subdir = find_newsletter_subdir(src_root)
    print(f"  Newsletter dir found")

    all_files = collect_md_files(subdir)
    print(f"  Found {len(all_files)} MD files")

    # Find hero image
    hero_img_src = ''
    main_img_dir = Path(src_root)
    for d in main_img_dir.iterdir():
        if d.is_dir():
            img = d / 'image.png'
            if img.exists():
                local = register_image(root_md if root_md else d / 'dummy.md', str(d.name + '/image.png'))
                # Use correct md_file for root image
                if root_md:
                    hero_img_src = register_image(root_md, unquote('%ED%95%9C%EA%B5%AD%EA%B5%90%EC%9C%A1%ED%95%99%ED%9A%8C%20%EC%A0%9C%EC%A3%BC%EC%A7%80%ED%9A%8C%20%EB%89%B4%EC%8A%A4%EB%A0%88%ED%84%B0/image.png'))
                break

    # Build sections
    print("  Building sections...")
    intro_html = build_intro_html(root_md)

    sections_parts = []
    for sec in SECTIONS:
        print(f"    {sec['title']}")
        sections_parts.append(build_section_html(sec, all_files))

    # Copy images
    print("  Copying images...")
    copy_all_images(out_dir)

    # Build TOC
    toc_html = build_toc()

    # Write output
    html = build_html(toc_html, intro_html, '\n'.join(sections_parts), hero_img_src)
    # Post-process: remove any remaining ** markdown bold markers
    html = html.replace('**', '')
    out_path = Path(out_dir) / 'index.html'
    with open(str(out_path), 'w', encoding='utf-8') as f:
        f.write(html)

    sz = out_path.stat().st_size
    img_count = len(list((Path(out_dir) / 'images').iterdir()))
    print(f"  Done!")
    print(f"  Output: {out_path}")
    print(f"  HTML size: {sz / 1024:.1f} KB")
    print(f"  Images copied: {img_count}")


def main():
    parser = argparse.ArgumentParser(description='Build newsletter HTML from Notion export')
    parser.add_argument('--src', default=DEFAULT_SRC,
                        help='Source directory (Notion export root)')
    parser.add_argument('--out', default=DEFAULT_OUT,
                        help='Output directory')
    args = parser.parse_args()
    build(args.src, args.out)


if __name__ == '__main__':
    main()

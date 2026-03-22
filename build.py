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
# Maps: source_abs_path (str) &rarr; local_relative_path (str, e.g. "images/xxx.png")
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
# Markdown &rarr; HTML helpers
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
            return m.group(0)  # already processed or external - leave unchanged
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

    # Links: [text](url) - skip CSV links
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
    """Convert the raw content inside <aside>...</aside> to HTML spans.
    If the aside contains a Notion icon (phone_green, feed_green, etc.),
    render as a small gray subtitle instead of a green aside block.
    """
    # Check if this is a Notion icon subtitle aside
    if 'notion.so/icons/' in content:
        # Extract just the text, remove icon img tag
        text = re.sub(r'<img[^>]+/?>', '', content)
        text = text.strip()
        # Apply inline (removes ** etc.)
        text = apply_inline(text, md_file)
        # Remove leading/trailing whitespace and tags
        text = re.sub(r'^\s*', '', text)
        return f'__SUBTITLE__{text}__/SUBTITLE__'

    lines = content.strip().split('\n')
    parts = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if re.match(r'^-{3,}$', s):
            parts.append('<hr>')
            continue
        # Strip markdown heading markers
        s = re.sub(r'^#{1,4}\s+', '', s)
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
                if '__SUBTITLE__' in aside_html:
                    # Render as small gray subtitle, not green aside block
                    text = aside_html.replace('__SUBTITLE__', '').replace('__/SUBTITLE__', '')
                    out.append(f'<p class="section-desc">{text}</p>\n')
                else:
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
            {'title': '구성원 소개', 'file_key': '제주지회 활동 소개 237', 'strip_content': ['주요 행사와 운영 계획', '2025 주요 활동', '제주지회 향후 계획']},
            {'title': '- 2025 주요 활동 -', 'file_key': '', 'is_divider': True},
            {'title': '창립 58주년 기념 강연 (2025.1.24.)', 'file_key': '창립 58주년 기념 강연'},
            {'title': '원도심마을탐방 (2025.4.26.)', 'file_key': '원도심마을탐방'},
            {'title': '2025 임원회의 (2025.9.12.)', 'file_key': '2025 임원회의'},
            {'title': '- 제주지회 향후 계획 -', 'file_key': '', 'is_divider': True},
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
            {'title': '- 제주대학교 아라캠퍼스 -', 'file_key': '', 'is_divider': True},
            {'title': '마을과 함께 가꾸는 교육의 터전', 'file_key': '마을과 함께 가꾸는 교육의 터전'},
            {'title': '2025 프론티어방 하계 워크숍', 'file_key': '2025 프론티어방 하계 워크숍'},
            {'title': '- 제주대학교 사라캠퍼스 -', 'file_key': '', 'is_divider': True},
            {'title': '2025 유럽 선진 숲 교육기관 연수', 'file_key': '2025 유럽 선진 숲 교육기관 연수'},
            {'title': '신입생 소개 - 이선아', 'file_key': '신입생 소개 26cf7f2dc41f80df'},
            {'title': '신입생 소개 - 김신회', 'file_key': '신입생 소개 28bf7f2dc41f80c5'},
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
    """Build level-2 section view (card list or direct content) and all level-3 article views.
    Returns (section_view_html, article_views_html).
    """
    sid = section['id']
    title = section['title']
    nav_title = section.get('nav_title', title)
    subtitle = section.get('subtitle', '')

    # -- Main content (sections with no subsections, e.g. 주론/시론) --
    main_content = ''
    if section.get('file_key'):
        main_file = find_file_by_key(all_files, section['file_key'])
        if main_file:
            md = strip_h1(read_md(main_file))
            md = re.sub(r'\[.+?\]\(.+?\.csv\)\n?', '', md)
            main_content = md_to_html(md, main_file)

    # -- Subsections &rarr; card list + article views --
    card_items_html = ''
    article_views = []

    if section.get('subsections'):
        card_parts = []
        for sub in section['subsections']:
            sub_title = sub['title']
            sub_key = sub.get('file_key', '')

            # Divider (group header) - kept as label in card list
            if sub.get('is_divider'):
                label = re.sub(r'^-\s*|-\s*$', '', sub_title).strip()
                card_parts.append(
                    f'<div class="subsection-divider">{escape_html(label)}</div>'
                )
                continue

            sub_file = find_file_by_key(all_files, sub_key) if sub_key else None
            if not sub_file:
                if sub_key:
                    print(f"  Warning: not found: '{sub_key}'")
                continue

            sub_md = read_md(sub_file)
            sub_md = strip_h1(sub_md)
            for strip_kw in sub.get('strip_content', []):
                def _remove_aside_only(text, kw):
                    parts = re.split(r'(<aside>.*?</aside>)', text, flags=re.DOTALL)
                    return ''.join(p for p in parts if not ('<aside>' in p and kw in p))
                sub_md = _remove_aside_only(sub_md, strip_kw)
                sub_md = re.sub(r'^#{1,4}\s+.*' + re.escape(strip_kw) + r'.*$', '', sub_md, flags=re.MULTILINE)
            sub_md = re.sub(r'\[.+?\]\(.+?\.csv\)\n?', '', sub_md)
            meta, sub_md = extract_metadata(sub_md)
            sub_id = slugify(sub_title)

            # Build meta label
            meta_parts = []
            if '제목' in meta:
                meta_parts.append(meta['제목'])
            elif '날짜' in meta:
                meta_parts.append(meta['날짜'])
            elif '연구실' in meta:
                meta_parts.append(meta['연구실'])
            meta_label = ' &#183; '.join(meta_parts)

            sub_html = md_to_html(sub_md, sub_file)

            # Card in card list (level-2)
            subtitle_span = (f'<div class="sub-subtitle">{escape_html(meta_label)}</div>'
                             if meta_label else '')
            card_parts.append(f'''<button class="sub-card" onclick="showArticle('{sid}','{sub_id}')" type="button">
  <div class="sub-card-body">
    <div class="sub-title">{escape_html(sub_title)}</div>
    {subtitle_span}
  </div>
  <span class="sub-card-arrow">&rarr;</span>
</button>''')

            # Article view (level-3)
            article_kicker_html = f'<div class="article-kicker">{escape_html(nav_title)}</div>'
            article_subtitle_html = (f'<div class="article-subtitle">{escape_html(meta_label)}</div>'
                                     if meta_label else '')
            article_views.append(f'''<div id="article-{sid}-{sub_id}" class="view">
  <div class="article-view">
    <div class="article-back-bar" onclick="backToSection()">
      <span class="back-arrow">&larr;</span> {escape_html(nav_title)} 목록으로
    </div>
    <div class="article-header">
      {article_kicker_html}
      <h1 class="article-title">{escape_html(sub_title)}</h1>
      {article_subtitle_html}
    </div>
    <div class="article-body">
      {sub_html}
    </div>
  </div>
</div>''')

        if card_parts:
            card_items_html = '<div class="card-list">' + '\n'.join(card_parts) + '</div>'

    # -- Build section view (level-2) --
    kicker_html = f'<div class="section-kicker">{escape_html(nav_title)}</div>' if nav_title != title else ''
    subtitle_html = (f'<p class="section-subtitle">{escape_html(subtitle)}</p>') if subtitle else ''

    if main_content and not card_items_html:
        # Direct content (주론, 시론 - no subsections)
        content_area = f'<div class="section-content">{main_content}</div>'
    elif card_items_html:
        content_area = card_items_html
    else:
        content_area = ''

    section_view = f'''<div id="view-{sid}" class="view">
  <div class="newsletter-section">
    <div class="section-header">
      {kicker_html}
      <h2 class="section-title">{escape_html(title)}</h2>
      {subtitle_html}
    </div>
    {content_area}
  </div>
</div>'''

    article_views_html = '\n'.join(article_views)
    return section_view, article_views_html


def build_intro_html(root_md_path, hero_image=''):
    if not root_md_path or not os.path.exists(str(root_md_path)):
        return ''
    md = read_md(root_md_path)
    md = strip_h1(md)
    # Remove CSV/database links
    md = re.sub(r'\[.+?\]\(.+?\.csv\)\n?', '', md)
    # Remove specific Notion aside blocks by splitting and filtering
    def remove_aside_blocks(text, keywords):
        parts = re.split(r'(<aside>.*?</aside>)', text, flags=re.DOTALL)
        return ''.join(p for p in parts if not any(kw in p for kw in keywords))
    md = remove_aside_blocks(md, ['cursor-click', 'Since 1993', '발행처', '후원'])
    # Remove first image (banner duplicate)
    md = re.sub(r'!\[image\.png\]\([^)]+\)\n?', '', md, count=1)
    # Remove footer-like content (cafe link, feedback email, etc.)
    md = re.sub(r'.*카페 바로가기.*\n?', '', md)
    md = re.sub(r'.*소중한 의견을 메일로.*\n?', '', md)
    md = re.sub(r'.*e\.yang@jejunu.*\n?', '', md)
    md = re.sub(r'.*뉴스레터 어떠셨나요.*\n?', '', md)
    content = md_to_html(md, root_md_path)
    hero_html = f'<img src="{hero_image}" alt="제주 하르방" loading="lazy" style="width:100%;border-radius:8px;margin-bottom:1.5rem;">' if hero_image else ''
    return f'''<div class="newsletter-section">
    <div class="section-header">
      <div class="section-kicker">발간사</div>
      <h2 class="section-title">발간의 글</h2>
    </div>
    <div class="section-content">
      {hero_html}
      {content}
    </div>
  </div>'''


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """
/* ============================================================
   Newsletter CSS - 한국교육학회 제주지회 (Modern Magazine)
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
    --gray-light:   #f6f7f8;
    --gray-mid:     #e4e8ec;
    --gray-text:    #64748b;
    --black:        #1e2630;
    --font-main:    'Noto Serif KR', 'NanumMyeongjo', Georgia, serif;
    --font-ui:      'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
    --shadow-sm:    0 1px 4px rgba(0,0,0,.07);
    --shadow-md:    0 4px 16px rgba(0,0,0,.10);
    --shadow-card:  0 2px 12px rgba(26,92,53,.10);
    --radius:       10px;
    --radius-card:  12px;
    --max-width:    960px;
    --transition:   0.2s ease;
}

html { scroll-behavior: smooth; font-size: 16px; }

body {
    font-family: var(--font-main);
    color: var(--black);
    background: var(--gray-light);
    line-height: 1.85;
    -webkit-font-smoothing: antialiased;
}

/* -- NAV -- */
nav.site-nav {
    position: sticky;
    top: 0;
    z-index: 200;
    background: var(--green-dark);
    box-shadow: 0 2px 12px rgba(0,0,0,.18);
}
.nav-inner {
    max-width: var(--max-width);
    margin: 0 auto;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0 1.5rem;
    height: 52px;
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}
.nav-brand {
    color: var(--white);
    font-family: var(--font-ui);
    font-size: 0.95rem;
    font-weight: 700;
    white-space: nowrap;
    text-decoration: none;
    flex-shrink: 0;
    letter-spacing: -0.01em;
    opacity: 0.92;
    transition: opacity var(--transition);
    cursor: pointer;
}
.nav-brand:hover { opacity: 1; }
.toc-list {
    display: flex;
    list-style: none;
    gap: 0;
    flex-wrap: nowrap;
    flex-shrink: 1;
    min-width: 0;
}
.toc-list a {
    color: rgba(255,255,255,0.7);
    text-decoration: none;
    font-family: var(--font-ui);
    font-size: 0.92rem;
    padding: 0.35rem 0.75rem;
    border-radius: 6px;
    transition: background var(--transition), color var(--transition);
    white-space: nowrap;
    display: block;
}
.toc-list a:hover {
    background: rgba(255,255,255,0.12);
    color: var(--white);
}
.toc-list a.active {
    background: rgba(255,255,255,0.18);
    color: var(--white);
    font-weight: 700;
}

/* -- MASTHEAD -- */
.masthead {
    background: #1a1a1a;
    color: var(--white);
    text-align: center;
    position: relative;
    overflow: hidden;
}
.masthead-inner {
    position: relative;
}
.masthead-eyebrow {
    font-family: var(--font-ui);
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.7);
    padding: 1rem 1.5rem 0.5rem;
    background: var(--green-dark);
}
.masthead-hero-img {
    width: 100%;
    line-height: 0;
}
.masthead-hero-img img {
    width: 100%;
    height: auto;
    display: block;
}
.masthead-meta {
    font-family: var(--font-ui);
    font-size: 0.85rem;
    color: rgba(255,255,255,0.8);
    padding: 0.8rem 1.5rem;
    background: var(--green-dark);
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    flex-wrap: wrap;
}
.masthead-meta .dot { opacity: 0.4; }

/* -- VIEW SHELL -- */
main {
    max-width: var(--max-width);
    margin: 0 auto;
    padding: 2rem 1.5rem 3rem;
    min-height: 60vh;
}

/* -- VIEWS (level 1, 2, 3) -- */
.view { display: none; }
.view.active { display: block; }

/* -- SECTION CARD (level-1 page) -- */
.newsletter-section {
    background: var(--white);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-sm);
    margin-bottom: 0;
    overflow: hidden;
    animation: fadeUp 0.25s ease both;
}
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
.section-header {
    padding: 2rem 2rem 1.25rem;
    border-bottom: 1px solid var(--gray-mid);
    background: var(--white);
}
.section-kicker {
    font-family: var(--font-ui);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--green-mid);
    margin-bottom: 0.4rem;
}
.section-title {
    font-size: 1.6rem;
    font-weight: 900;
    color: var(--black);
    font-family: var(--font-ui);
    line-height: 1.25;
    word-break: keep-all;
    letter-spacing: -0.02em;
}
.section-desc {
    font-size: 0.85rem;
    color: var(--gray-text);
    font-family: var(--font-ui);
    margin-top: 0.5rem;
    line-height: 1.6;
}
.section-subtitle {
    font-family: var(--font-ui);
    font-size: 0.88rem;
    color: var(--green-mid);
    margin-top: 0.3rem;
    line-height: 1.5;
}
.section-content {
    padding: 1.75rem 2rem;
    overflow-wrap: break-word;
    word-break: keep-all;
}

/* -- TYPOGRAPHY (article content) -- */
.article-body h1,
.article-body h2,
.article-body h3,
.article-body h4,
.section-content h1,
.section-content h2,
.section-content h3,
.section-content h4 {
    font-family: var(--font-ui);
    color: var(--green-dark);
    margin: 1.75rem 0 0.65rem;
    line-height: 1.4;
}
.article-body h1, .section-content h1 {
    font-size: 1.3rem;
    padding-bottom: 0.4rem;
    border-bottom: 2px solid var(--green-pale);
}
.article-body h2, .section-content h2 { font-size: 1.15rem; }
.article-body h3, .section-content h3 { font-size: 1.02rem; }
.article-body h4, .section-content h4 { font-size: 0.95rem; color: var(--green-mid); }

.article-body p,
.section-content p {
    margin-bottom: 1.1rem;
    line-height: 2;
    color: #2c3440;
    font-size: 1rem;
}
.article-body strong,
.section-content strong { color: var(--green-dark); font-weight: 700; }
.article-body em,
.section-content em { font-style: italic; }
.article-body code,
.section-content code {
    background: var(--green-pale);
    color: var(--green-dark);
    padding: 0.1em 0.4em;
    border-radius: 4px;
    font-family: var(--font-ui);
    font-size: 0.85em;
}
.article-body hr,
.section-content hr {
    border: none;
    border-top: 1px solid var(--gray-mid);
    margin: 2rem 0;
}
.article-body blockquote,
.section-content blockquote {
    border-left: 3px solid var(--green-light);
    padding: 0.85rem 1.25rem;
    margin: 1.25rem 0;
    background: var(--green-faint);
    border-radius: 0 var(--radius) var(--radius) 0;
    font-style: italic;
    color: var(--gray-text);
}
.article-body ul, .article-body ol,
.section-content ul, .section-content ol {
    padding-left: 1.6rem;
    margin-bottom: 1.1rem;
}
.article-body li,
.section-content li { margin-bottom: 0.35rem; line-height: 1.85; }
.article-body a,
.section-content a {
    color: var(--green-mid);
    text-decoration: underline;
    text-decoration-color: var(--green-pale);
    transition: color var(--transition);
}
.article-body a:hover,
.section-content a:hover { color: var(--green-dark); }

/* -- IMAGES -- */
.article-body img,
.section-content img {
    max-width: 100%;
    height: auto;
    border-radius: var(--radius-card);
    display: block;
    margin: 1.5rem auto;
    box-shadow: var(--shadow-sm);
}
.article-body img[alt*="교수"],
.article-body img[alt*="선생님"],
.article-body img[alt*="사진"],
.article-body img[alt*="증명"],
.section-content img[alt*="교수"],
.section-content img[alt*="선생님"],
.section-content img[alt*="사진"],
.section-content img[alt*="증명"] {
    max-width: 150px;
    border-radius: 50%;
    object-fit: cover;
    aspect-ratio: 1;
    object-position: top;
    box-shadow: 0 2px 10px rgba(0,0,0,.12);
}

/* -- FIGURE CAPTIONS -- */
.figure-caption {
    font-size: 0.85rem;
    color: #666;
    text-align: center;
    font-family: var(--font-ui);
    margin: 0.5rem 0 1.5rem;
    line-height: 1.5;
}

/* -- FOOTNOTES -- */
.fn-ref a {
    color: var(--green-mid);
    text-decoration: none;
    font-weight: 600;
}
.fn-ref a:hover { text-decoration: underline; }
.footnote-def {
    font-size: 0.85rem;
    color: var(--gray-text);
    padding: 0.5rem 0;
    border-top: 1px solid var(--gray-mid);
    line-height: 1.6;
}
.footnote-def .fn-num {
    font-weight: 700;
    color: var(--green-dark);
}
.fn-back {
    color: var(--green-mid);
    text-decoration: none;
    font-size: 0.8rem;
}

/* -- REFERENCE LIST (참고문헌) -- */
.ref-list {
    margin: 0.5rem 0 1.5rem 0;
}
.ref-list p {
    padding-left: 2em;
    text-indent: -2em;
    margin: 0.35rem 0;
    font-size: 0.93rem;
    line-height: 1.75;
    color: var(--black);
    word-break: keep-all;
}

/* -- ASIDE BLOCKS -- */
.aside-block {
    background: var(--gray-light);
    border: 1px solid var(--gray-mid);
    border-radius: var(--radius-card);
    padding: 1.1rem 1.4rem;
    margin: 1.25rem 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
}
.aside-block span {
    display: block;
    font-size: 0.93rem;
    color: var(--gray-text);
    line-height: 1.75;
    word-break: keep-all;
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
    max-width: 110px;
    border-radius: 50%;
    display: block;
    margin: 0.25rem auto;
    box-shadow: none;
}

/* -- TABLES -- */
.table-wrap {
    overflow-x: auto;
    margin: 1.5rem 0;
    border-radius: var(--radius);
    border: 1px solid var(--gray-mid);
}
table {
    border-collapse: collapse;
    width: 100%;
    min-width: 600px;
    font-family: var(--font-ui);
    font-size: 0.88rem;
}
th {
    background: var(--green-dark);
    color: var(--white);
    padding: 0.7rem 1rem;
    text-align: left;
    font-weight: 600;
    white-space: nowrap;
}
td {
    padding: 0.6rem 1rem;
    border-bottom: 1px solid var(--gray-mid);
    vertical-align: top;
    line-height: 1.65;
    word-break: keep-all;
    overflow-wrap: break-word;
}
tr:last-child td { border-bottom: none; }
tr:nth-child(even) td { background: #fafbfc; }
tr:hover td { background: var(--green-faint); }

/* -- CARD LIST (level-2: subsection list) -- */
.card-list {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 1.5rem 2rem;
}
.subsection-divider {
    padding: 1.1rem 0 0.35rem;
    font-family: var(--font-ui);
    font-size: 0.73rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--green-mid);
    border-top: 1px solid var(--gray-mid);
    margin-top: 0.5rem;
}
.subsection-divider:first-child {
    padding-top: 0;
    border-top: none;
    margin-top: 0;
}
.sub-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 1.25rem;
    background: var(--white);
    border: 1px solid var(--gray-mid);
    border-radius: var(--radius);
    cursor: pointer;
    transition: border-color var(--transition), box-shadow var(--transition), transform var(--transition);
    text-align: left;
    text-decoration: none;
    color: inherit;
}
.sub-card:hover {
    border-color: var(--green-light);
    box-shadow: var(--shadow-card);
    transform: translateY(-1px);
}
.sub-card-body { flex: 1; min-width: 0; }
.sub-title {
    font-family: var(--font-ui);
    font-weight: 700;
    font-size: 0.97rem;
    color: var(--black);
    line-height: 1.4;
    word-break: keep-all;
}
.sub-subtitle {
    font-family: var(--font-ui);
    font-size: 0.82rem;
    color: var(--gray-text);
    margin-top: 0.2rem;
    line-height: 1.5;
}
.sub-card-arrow {
    color: var(--green-light);
    font-size: 1rem;
    flex-shrink: 0;
    transition: color var(--transition), transform var(--transition);
}
.sub-card:hover .sub-card-arrow {
    color: var(--green-dark);
    transform: translateX(3px);
}

/* -- ARTICLE VIEW (level-3) -- */
.article-view {
    background: var(--white);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-sm);
    overflow: hidden;
    animation: fadeUp 0.22s ease both;
}
.article-back-bar {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.85rem 1.75rem;
    background: var(--gray-light);
    border-bottom: 1px solid var(--gray-mid);
    font-family: var(--font-ui);
    font-size: 0.83rem;
    color: var(--green-dark);
    cursor: pointer;
    transition: background var(--transition);
    user-select: none;
}
.article-back-bar:hover { background: var(--green-pale); }
.article-back-bar .back-arrow { font-size: 1.05rem; }
.article-header {
    padding: 2rem 2rem 1.25rem;
    border-bottom: 1px solid var(--gray-mid);
}
.article-kicker {
    font-family: var(--font-ui);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--green-mid);
    margin-bottom: 0.5rem;
}
.article-title {
    font-family: var(--font-ui);
    font-size: 1.5rem;
    font-weight: 900;
    color: var(--black);
    line-height: 1.3;
    letter-spacing: -0.02em;
    word-break: keep-all;
}
.article-subtitle {
    font-family: var(--font-ui);
    font-size: 0.88rem;
    color: var(--gray-text);
    margin-top: 0.5rem;
}
.article-body {
    padding: 1.75rem 2rem 2.5rem;
    overflow-wrap: break-word;
    word-break: keep-all;
    max-width: 680px;
}

/* -- FOOTER -- */
footer {
    background: var(--green-dark);
    color: rgba(255,255,255,0.8);
    padding: 2.5rem 1.5rem 2rem;
    text-align: center;
    font-family: var(--font-ui);
    font-size: 0.85rem;
    margin-top: 3rem;
}
.footer-inner { max-width: var(--max-width); margin: 0 auto; }
.footer-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem 1.5rem;
    text-align: left;
    margin-bottom: 1.5rem;
}
.footer-item label {
    display: block;
    color: var(--green-pale);
    font-size: 0.7rem;
    font-weight: 700;
    margin-bottom: 0.2rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
.footer-item span, .footer-item a {
    color: rgba(255,255,255,0.8);
    text-decoration: none;
    line-height: 1.6;
    font-size: 0.85rem;
}
.footer-item a:hover { color: var(--green-pale); }
.footer-contact-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
}
.footer-contact-item label {
    display: block;
    color: var(--green-pale);
    font-size: 0.7rem;
    font-weight: 700;
    margin-bottom: 0.3rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
.footer-contact-item > span {
    color: rgba(255,255,255,0.8);
    font-size: 0.85rem;
    text-decoration: none;
    line-height: 1.6;
}
.footer-contact-item > span a {
    color: rgba(255,255,255,0.8);
    text-decoration: none;
}
.footer-contact-item > span a:hover { color: var(--green-pale); }
.footer-contact-item a:hover { color: var(--green-pale); }
.footer-divider { border: none; border-top: 1px solid rgba(255,255,255,0.12); margin: 1.25rem 0; }
.footer-copy { font-size: 0.77rem; opacity: 0.45; }
.feedback-box {
    background: rgba(255,255,255,0.06);
    border-radius: var(--radius);
    padding: 1rem 1.25rem;
    margin: 0 0 1rem;
    font-size: 0.84rem;
    line-height: 1.9;
    text-align: left;
    border: 1px solid rgba(255,255,255,0.1);
}
.feedback-box a { color: var(--green-pale); }
.donation-box { font-size: 0.79rem; opacity: 0.65; margin-bottom: 0.5rem; }

/* -- BACK TO TOP -- */
.back-top {
    position: fixed;
    bottom: 1.75rem;
    right: 1.75rem;
    background: var(--green-dark);
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
    transition: background var(--transition), transform var(--transition);
    opacity: 0.85;
    z-index: 50;
}
.back-top:hover { background: var(--green-mid); transform: translateY(-2px); opacity: 1; }

/* -- RESPONSIVE -- */
@media (max-width: 640px) {
    .nav-inner {
        padding: 0 0.75rem;
        height: 48px;
    }
    .nav-brand { font-size: 0.72rem; }
    .toc-list a { font-size: 0.75rem; padding: 0.25rem 0.45rem; }
    main { padding: 1rem 0.875rem 2rem; }
    .masthead-eyebrow { font-size: 0.68rem; padding: 0.8rem 1rem 0.4rem; }
    .masthead-meta { font-size: 0.78rem; padding: 0.6rem 1rem; }
    .section-header,
    .article-header { padding: 1.25rem 1.25rem 1rem; }
    .section-content,
    .article-body { padding: 1.25rem 1.25rem 1.75rem; }
    .card-list { padding: 1rem 1.25rem; }
    .article-back-bar { padding: 0.75rem 1.25rem; }
    .footer-grid { grid-template-columns: 1fr; gap: 0.8rem; }
    .footer-contact-grid { grid-template-columns: 1fr; }
    .section-title { font-size: 1.35rem; }
    .article-title { font-size: 1.25rem; }
}

@media print {
    nav.site-nav, .back-top, .article-back-bar { display: none !important; }
    .view { display: block !important; }
    .newsletter-section { box-shadow: none; border: 1px solid #ccc; page-break-inside: avoid; }
    .sub-card { page-break-inside: avoid; }
}

"""

# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------
INLINE_JS = """
// 3-level drill-down navigation
// Level 1: top tabs  - view-{id}   (shows section card with card-list or full content)
// Level 2: card list - article-{sectionId}-{subId}  (shows article view)
// Level 3: article   - back button returns to level 2

var _currentSection = 'intro';

// Show a level-1 view (section index or intro)
function showSection(id) {
  document.querySelectorAll('.view').forEach(function(v) { v.classList.remove('active'); });
  var view = document.getElementById('view-' + id);
  if (view) view.classList.add('active');
  _currentSection = id;

  // Update nav active state
  document.querySelectorAll('.toc-list a').forEach(function(a) { a.classList.remove('active'); });
  var link = document.querySelector('.toc-list a[data-section="' + id + '"]');
  if (link) link.classList.add('active');

  // Show/hide hero banner (only on intro page)
  var heroImg = document.querySelector('.masthead-hero-img');
  if (heroImg) heroImg.style.display = (id === 'intro') ? '' : 'none';

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Show a level-3 article within a section
function showArticle(sectionId, subId) {
  // Hide the section view
  document.querySelectorAll('.view').forEach(function(v) { v.classList.remove('active'); });

  // Show the article view
  var art = document.getElementById('article-' + sectionId + '-' + subId);
  if (art) {
    art.classList.add('active');
    _currentSection = sectionId;
    var heroImg = document.querySelector('.masthead-hero-img');
    if (heroImg) heroImg.style.display = 'none';
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

// Back from article to section list
function backToSection() {
  showSection(_currentSection);
}

// Nav click handlers
document.querySelectorAll('.toc-list a').forEach(function(a) {
  a.addEventListener('click', function(e) {
    e.preventDefault();
    var sectionId = a.getAttribute('data-section');
    if (sectionId) showSection(sectionId);
  });
});

// Show intro by default
showSection('intro');
"""


# ---------------------------------------------------------------------------
# Full HTML template
# ---------------------------------------------------------------------------

def build_html(toc_html, intro_html, sections_html, article_views_html, hero_img_src):
    hero = ''
    if hero_img_src:
        hero = f'<div class="masthead-hero-img"><img src="{hero_img_src}" alt="뉴스레터 헤더 이미지"></div>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{NEWSLETTER_TITLE} {NEWSLETTER_SUBTITLE} {PUBLICATION_DATE}">
  <title>{NEWSLETTER_TITLE} | {NEWSLETTER_SUBTITLE}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;900&family=Noto+Sans+KR:wght@400;600;700&display=swap" rel="stylesheet">
  <style>{CSS}</style>
</head>
<body>

<!-- NAVIGATION -->
<nav class="site-nav" role="navigation" aria-label="목차">
  <div class="nav-inner">
    <a class="nav-brand" href="#" onclick="event.preventDefault(); showSection('intro');">제주교육마루</a>
    {toc_html}
  </div>
</nav>

<!-- MASTHEAD -->
<header class="masthead" role="banner">
  <div class="masthead-inner">
    <div class="masthead-eyebrow">{SINCE} &#183; {NEWSLETTER_SUBTITLE}</div>
    {hero}
    <div class="masthead-meta">
      <span>{NEWSLETTER_TITLE}</span>
      <span class="dot">&#183;</span>
      <span>{PUBLICATION_DATE}</span>
    </div>
  </div>
</header>

<!-- CONTENT (all views, JS shows/hides) -->
<main>
  <!-- Level 1: Intro -->
  <div id="view-intro" class="view">
    {intro_html}
  </div>

  <!-- Level 1+2: Section views (card list or direct content) -->
  {sections_html}

  <!-- Level 3: Article views -->
  {article_views_html}
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
        <a href="{CAFE_URL}" target="_blank" rel="noopener">한국교육학회 제주지회 카페 &rarr;</a>
      </div>
    </div>
    <hr class="footer-divider">
    <div class="feedback-box">
      <p style="margin-bottom:1.2rem;">이번 뉴스레터 어떠셨나요? 여러분의 생각과 의견을 기다립니다. 소중한 의견을 메일로 보내주시면 다음 호에 적극 반영하겠습니다.</p>
      <div class="footer-contact-grid">
        <div class="footer-contact-item">
          <label>뉴스레터 문의</label>
          <span><a href="mailto:{FEEDBACK_EMAIL}">{FEEDBACK_EMAIL}</a> ({FEEDBACK_NAME})</span>
        </div>
        <div class="footer-contact-item">
          <label>뉴스레터 후원</label>
          <span>{DONATION_ACCOUNT}</span>
        </div>
      </div>
    </div>
    <hr class="footer-divider">
    <p class="footer-copy">&copy; 2025 {PUBLISHER}. All rights reserved.</p>
  </div>
</footer>

<a href="#" class="back-top" aria-label="맨 위로">&uarr;</a>

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

    # Hero image: use banner.jpg if it exists, otherwise find from export
    banner_path = Path(out_dir) / 'images' / 'banner.jpg'
    if banner_path.exists():
        hero_img_src = 'images/banner.jpg'
    else:
        hero_img_src = ''
        main_img_dir = Path(src_root)
        for d in main_img_dir.iterdir():
            if d.is_dir():
                img = d / 'image.png'
                if img.exists():
                    if root_md:
                        hero_img_src = register_image(root_md, unquote('%ED%95%9C%EA%B5%AD%EA%B5%90%EC%9C%A1%ED%95%99%ED%9A%8C%20%EC%A0%9C%EC%A3%BC%EC%A7%80%ED%9A%8C%20%EB%89%B4%EC%8A%A4%EB%A0%88%ED%84%B0/image.png'))
                    break
    # Register the old hero (하르방) for use in intro
    old_hero_src = ''
    if root_md:
        old_hero_src = register_image(root_md, unquote('%ED%95%9C%EA%B5%AD%EA%B5%90%EC%9C%A1%ED%95%99%ED%9A%8C%20%EC%A0%9C%EC%A3%BC%EC%A7%80%ED%9A%8C%20%EB%89%B4%EC%8A%A4%EB%A0%88%ED%84%B0/image.png'))

    # Build sections
    print("  Building sections...")
    intro_html = build_intro_html(root_md, hero_image=old_hero_src)

    sections_parts = []
    all_article_views = []
    for sec in SECTIONS:
        print(f"    {sec['title']}")
        sec_view, art_views = build_section_html(sec, all_files)
        sections_parts.append(sec_view)
        if art_views:
            all_article_views.append(art_views)

    # Copy images
    print("  Copying images...")
    copy_all_images(out_dir)

    # Build TOC
    toc_html = build_toc()

    # Write output
    html = build_html(toc_html, intro_html, '\n'.join(sections_parts),
                      '\n'.join(all_article_views), hero_img_src)
    # Post-process: remove any remaining ** markdown bold markers
    html = html.replace('**', '')
    # Fix split titles: H1 followed by a <p> that continues the title
    html = re.sub(
        r'<h1[^>]*>제주교육의 정체성 구현과</h1>\s*<p>제주지회의 활성화</p>',
        '', html)
    html = re.sub(
        r'<h1[^>]*>제주도 교육 특별자치,</h1>\s*<p>이제 어드레 가멘\??</p>',
        '', html)
    html = re.sub(
        r'<h1[^>]*>\[수업사례 나눔\]</h1>\s*<p>손끝으로 만드는 음악 세상</p>',
        '', html)
    # Remove consecutive empty hrs and blank aside blocks
    html = re.sub(r'(<hr>\s*){2,}', '<hr>', html)
    # Remove empty paragraphs and empty blockquotes
    html = re.sub(r'<p>\s*</p>', '', html)
    html = re.sub(r'<blockquote>\s*</blockquote>', '', html)
    # Footnotes: convert <code>[N]</code> inline to superscript links,
    # and <p><code>[N]</code> text</p> to footnote definitions.
    # Process each view section separately to avoid duplicate IDs across articles.
    def process_footnotes(html_text, prefix=''):
        """Process footnotes in a single article's HTML.
        prefix: a string to namespace IDs, e.g. 'juron-' → fn-juron-1, fnref-juron-1
        Rules:
          - <p><code>[N]</code> SOME TEXT</p>  →  footnote definition (requires non-empty text)
          - <p><code>[N]</code></p>             →  standalone inline ref (no text = not a def)
          - <code>[N]</code> anywhere remaining →  inline superscript reference
        """
        # Step 1: footnote definitions – only when there is actual text after the number
        fn_def_pattern = r'<p><code>\[(\d+)\]</code>\s+(.+?)</p>'
        def fn_def_replace(m):
            num = m.group(1)
            text = m.group(2).strip()
            pid = f'fn-{prefix}{num}'
            rid = f'fnref-{prefix}{num}'
            return (f'<div class="footnote-def" id="{pid}">'
                    f'<span class="fn-num">[{num}]</span> {text} '
                    f'<a href="#{rid}" class="fn-back">↩</a></div>')
        html_text = re.sub(fn_def_pattern, fn_def_replace, html_text, flags=re.DOTALL)

        # Step 2: standalone <p><code>[N]</code></p> (no text) → inline superscript ref
        fn_standalone_pattern = r'<p>\s*<code>\[(\d+)\]</code>\s*</p>'
        def fn_standalone_replace(m):
            num = m.group(1)
            pid = f'fn-{prefix}{num}'
            rid = f'fnref-{prefix}{num}'
            return f'<sup class="fn-ref" id="{rid}"><a href="#{pid}">[{num}]</a></sup>'
        html_text = re.sub(fn_standalone_pattern, fn_standalone_replace, html_text)

        # Step 3: remaining inline <code>[N]</code> → superscript ref (no duplicate id if already set)
        def fn_ref_replace(m):
            num = m.group(1)
            pid = f'fn-{prefix}{num}'
            rid = f'fnref-{prefix}{num}'
            return f'<sup class="fn-ref" id="{rid}"><a href="#{pid}">[{num}]</a></sup>'
        html_text = re.sub(r'<code>\[(\d+)\]</code>', fn_ref_replace, html_text)
        return html_text

    def convert_ref_lists(html_text):
        """Convert <ul><li>...</li></ul> that immediately follow a 참고문헌 heading
        into hanging-indent <div class="ref-list"><p>...</p></div> blocks."""
        html_text = re.sub(
            r'(<h3[^>]*id="참고문헌"[^>]*>참고문헌</h3>\s*)<ul>(.*?)</ul>',
            lambda m: m.group(1) + '<div class="ref-list">' + ''.join(
                f'<p>{item.strip()}</p>'
                for item in re.findall(r'<li>(.*?)</li>', m.group(2), re.DOTALL)
            ) + '</div>',
            html_text, flags=re.DOTALL)
        return html_text

    # Process each view section's footnotes with a unique prefix to avoid ID collisions
    def process_all_footnotes(html_text):
        # Split HTML into view sections and process each separately
        # Pattern: <div id="view-SECTIONID" ...> ... </div>
        # We'll find each view's boundaries and process footnotes within each
        result_parts = []
        last_end = 0
        for m in re.finditer(r'<div\s+id="view-([^"]+)"', html_text):
            prefix = m.group(1) + '-'
            start = m.start()
            # Append text before this view unchanged
            result_parts.append(html_text[last_end:start])
            # Find the extent of this view's content up to the next top-level view div
            # We just need to find the matching close; use a simpler heuristic:
            # process from this view start to the next <div id="view-"> or end
            next_view = re.search(r'<div\s+id="view-', html_text[m.end():])
            if next_view:
                view_end = m.end() + next_view.start()
            else:
                view_end = len(html_text)
            view_html = html_text[start:view_end]
            view_html = process_footnotes(view_html, prefix)
            result_parts.append(view_html)
            last_end = view_end
        result_parts.append(html_text[last_end:])
        return ''.join(result_parts)

    html = process_all_footnotes(html)
    html = convert_ref_lists(html)

    # Convert all <ul><li> after 저서/논문/연구물 headings to ref-list too
    html = re.sub(
        r'(<h3[^>]*>(?:저서|그 외 공저서|논문|정책연구)[^<]*</h3>\s*)<ul>(.*?)</ul>',
        lambda m: m.group(1) + '<div class="ref-list">' + ''.join(
            f'<p>{item.strip()}</p>'
            for item in re.findall(r'<li>(.*?)</li>', m.group(2), re.DOTALL)
        ) + '</div>',
        html, flags=re.DOTALL)

    # Convert <code><표 N> ...</code> and <code>[그림 N] ...</code> to caption style
    html = re.sub(
        r'<p><code>(&lt;표\s*\d+&gt;[^<]*|<표[^<]*|\[그림\s*\d+\][^<]*)</code></p>',
        r'<p class="figure-caption">\1</p>', html)

    # Fix 주론 <표 2> - replace broken table with correct HTML
    table2_html = '''<div class="table-wrap"><table>
<thead><tr><th>연대</th><th>주요 활동</th><th>특이 사항</th></tr></thead>
<tbody>
<tr><td>1960년대</td><td>-1967. 1월. 제주지회 창립<br>-1967. 12월. 연구발표회(제주도교육의 역사적 배경; 오늘의 Veitnam교육)<br>-1968. 11월. 연구발표회(아세아 각국의 교과과정을 규제하는 언어적, 종교적 요인; 부모의 교육태도가 자녀의 성격형성에 미치는 영향; 제주도 중등학교 수학교과교육의 제문제)<br>-1969. 12월. 연구발표회(낙후지 추자도의 향토문제에 관한 연구)</td><td>-1970~1973년 사이의 연구발표회가 확인되지 않음.<br>-임원은 회장, 이사, 감사로 구성. 창립부터 1972년까지 동일인이 회장이었고, 5명의 이사도 동일인으로 나타남.<br>-창립일이 기록에 따라 다름(1/24, 1/28, 2/1).</td></tr>
<tr><td>1970년대</td><td>-1973. 3월. 지회 임시총회<br>-1974. 8월. 연구발표회(청년기의 정서적 발달과 그 지도안)<br>-1975. 12월. 연구발표회(민족주체성 교육에 있어서 주체성 개념 모형)</td><td>-지회 활동 정상화<br>-연구발표회 동·하계로 확대</td></tr>
<tr><td>1980년대</td><td>-1984. 2월. 연구발표회(주제 미확인됨)<br>-1988. 2월. 정기총회 및 연구발표회(주제 미확인됨)</td><td>-제주대 교육대학원과 한국교원대 중심으로 회원 증가<br>-지회활동의 활기 찾음</td></tr>
<tr><td>1990년대</td><td>-&lt;한국교육학회 제주지회 소식&gt; 뉴스레터 발간<br>-연구발표지 출간 고려</td><td>-질적 측면 강화<br>-지회 정체성 논의<br>-제주교육대학교 교육대학원 개원</td></tr>
<tr><td>2000년대</td><td>-2007. 11월. 한국교육학회 연차학술대회 제주 개최<br>-2018. 6월. 한국교육학회 연차학술대회 제주 개최<br>-2023. 6월. 제주지회 활성화 추진, 김민호 신임회장 선출<br>-2023. 12월. 제주교육학 학술대회 공동주관<br>-2024. 11월. 제주교육학 학술대회 공동주관<br>-2025. 1월. 신진학자·정년기념 강연<sup class="fn-ref" id="fnref-juron-1"><a href="#fn-juron-1">[1]</a></sup><br>-2025. 4월. 원도심마을탐방 행사<br>-2025. 10월. 제주지회 뉴스레터 재창간 예정</td><td>-지회활동 장기간 비활성화<br>-제주지회 활성화 추진<br>-지회 조직정비(부회장, 소위원회 등) 및 4대 활동영역 구조화<br>-제주교육학연구회와 협업체제 구축</td></tr>
</tbody></table></div>'''
    # Find and replace the broken table section
    html = re.sub(
        r'<p class="figure-caption"><표 2> 제주지회 주요 활동 연혁</p>.*?<p>이를 종합하면',
        f'<p class="figure-caption">&lt;표 2&gt; 제주지회 주요 활동 연혁</p>\n{table2_html}\n<p>이를 종합하면',
        html, flags=re.DOTALL)

    # Fix 회장 info: merge phone/email spans into one line
    html = re.sub(
        r'<span>- 전화번호: ([^<]+)</span>\s*<span>- 이메일:\s*([^<]+)</span>',
        r'<span>- 전화번호: \1 | 이메일: \2</span>', html)

    # 시론 specific fixes:
    # [1] move to title
    html = html.replace(
        '제주도 교육 특별자치, 이제 어드레 가멘?</h2>',
        '제주도 교육 특별자치, 이제 어드레 가멘?<sup class="fn-ref" id="fnref-siron-1"><a href="#fn-siron-1">[1]</a></sup></h2>')
    # Remove the standalone [1] that was floating
    html = re.sub(r'\n<sup class="fn-ref" id="fnref-siron-1">.*?</sup>\n', '\n', html, count=1)

    # [2] extended definition - merge following paragraphs into footnote, move ↩ to end
    def fix_fn2(m):
        before_back = m.group(1)  # text before ↩ link
        back_link = m.group(2)    # the ↩ link
        after_div = m.group(3)    # </div>
        p1 = m.group(4)           # first continuation paragraph
        p2 = m.group(5)           # second continuation paragraph
        return f'{before_back} {p1} {p2} {back_link}{after_div}'
    html = re.sub(
        r'(발전방안이었다\.)\s*(<a href="#fnref-siron-2"[^>]*>↩</a>)(</div>)\s*<p>(보고서의 핵심 결론은.*?)</p>\s*<p>(보고서는 개선안으로.*?)</p>',
        fix_fn2,
        html, flags=re.DOTALL)

    # [6],[7] in code block - convert to proper refs
    html = html.replace(
        '<code>미활용 [6] , 미제정 [7]</code>',
        '미활용<sup class="fn-ref" id="fnref-siron-6"><a href="#fn-siron-6">[6]</a></sup>, '
        '미제정<sup class="fn-ref" id="fnref-siron-7"><a href="#fn-siron-7">[7]</a></sup>')

    # [14] in heading - fix backtick remnant
    html = re.sub(
        r'(<h3[^>]*>5\. 제주 교육자치 20여 년 궤적에서 어떤 반면교사를 삼을 것인가\?)`\[14\]`</h3>',
        r'\1<sup class="fn-ref" id="fnref-siron-14"><a href="#fn-siron-14">[14]</a></sup></h3>',
        html)

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

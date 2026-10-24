"""Readable Markdown and paginated, source-linked PDF briefing exports."""
from __future__ import annotations

from io import BytesIO
import logging
import os
from pathlib import Path
import re
from xml.sax.saxutils import escape

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Table, TableStyle
from utils.config import ResearchError
from comparison_app.models import Briefing, Claim
from utils.common import configure_logging, get_required_env

log = configure_logging()
NAVY = colors.HexColor('#152B46')
TEAL = colors.HexColor('#087F8C')


def citation_numbers(briefing: Briefing) -> dict[str, int]:
    """Use short, consistent citation numbers in both PDF and screen briefings."""
    return {source.id: number for number, source in enumerate(briefing.sources, 1)}


def claim_text(claim: Claim, references: dict[str, int]) -> str:
    """Label inference and unknown findings without exposing private reasoning."""
    prefix = {'fact': '', 'inference': 'Assessment: ', 'unknown': 'Unverified: '}[claim.kind]
    citations = ' '.join(f'[{references[source]}]' for source in claim.source_ids if source in references)
    return f'{prefix}{claim.text} {citations}'.strip()


def markdown_briefing(briefing: Briefing) -> str:
    """Render the exact structured artifacts without a second ungrounded LLM rewrite."""
    references = citation_numbers(briefing)
    lines = [f'# {briefing.company}: competitor analysis',
             f'As of {briefing.generated_at[:10]} (UTC) · Run {briefing.run_id}',
             f'\nMarket scope: {briefing.market_scope}']
    if briefing.demo:
        lines.append('\n**SYNTHETIC DEMO - not real market research.**')
    lines.append('\n## Executive briefing')
    lines.extend('- ' + claim_text(claim, references) for claim in briefing.synthesis.executive_summary)
    lines.append('\n## Competitor selection')
    for competitor in briefing.discovery.competitors:
        lines.append(f'- **{competitor.name}**: {claim_text(competitor.rationale, references)}')
    for profile in [briefing.target, *briefing.competitors]:
        lines.append(f'\n## {profile.company}')
        for heading, claims in [('Pricing', profile.pricing), ('Core features', profile.features),
                                ('Market positioning', profile.positioning), ('Recent news', profile.news)]:
            lines.append(f'\n### {heading}')
            lines.extend('- ' + claim_text(claim, references) for claim in claims)
        lines.extend(f'- Gap: {gap}' for gap in profile.gaps)
    for heading, claims in [('Opportunities', briefing.synthesis.opportunities), ('Risks', briefing.synthesis.risks)]:
        lines.append(f'\n## {heading}')
        lines.extend('- ' + claim_text(claim, references) for claim in claims)
    lines.append('\n## Limitations and collection notes')
    lines.extend('- ' + note for note in [*briefing.synthesis.limitations, *briefing.warnings])
    lines.append('\n## Sources')
    for source in briefing.sources:
        lines.append(f'{references[source.id]}. {source.title} — {source.url} '
                     f'(published: {source.published_at or "not supplied"}; retrieved: {source.retrieved_at})')
    return '\n'.join(lines)


def filename(company: str) -> str:
    """Build a bounded download filename without path traversal or control characters."""
    safe = re.sub(r'[^a-zA-Z0-9_-]+', '-', company).strip('-')[:70] or 'company'
    return f'{safe.lower()}-competitor-briefing.pdf'


def pdf_briefing(briefing: Briefing) -> bytes:
    """Generate a multi-page briefing with wrapped tables, citations and page numbers."""
    try:
        bundled = Path(reportlab.__file__).parent / 'fonts'
        regular = os.getenv('P3_PDF_FONT_PATH') or str(bundled / 'Vera.ttf')
        bold = os.getenv('P3_PDF_BOLD_FONT_PATH') or str(bundled / 'VeraBd.ttf')
        pdfmetrics.registerFont(TTFont('ResearchBody', regular))
        pdfmetrics.registerFont(TTFont('ResearchBold', bold))
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='ResearchTitle', fontName='ResearchBold', fontSize=24,
                                  leading=29, textColor=NAVY, spaceAfter=14))
        styles.add(ParagraphStyle(name='ResearchHeading', fontName='ResearchBold', fontSize=13,
                                  leading=17, textColor=NAVY, spaceBefore=16, spaceAfter=8, keepWithNext=True))
        styles.add(ParagraphStyle(name='ResearchBody', fontName='ResearchBody', fontSize=9,
                                  leading=14, spaceAfter=7, splitLongWords=True))
        styles.add(ParagraphStyle(name='ResearchSmall', parent=styles['ResearchBody'], fontSize=7.5,
                                  leading=11, wordWrap='CJK'))
        styles.add(ParagraphStyle(name='ResearchLabel', parent=styles['ResearchSmall'], keepWithNext=True))
        refs = citation_numbers(briefing)
        story = []

        def paragraph(text: str, style='ResearchBody') -> Paragraph:
            """Escape source/model text so it cannot inject PDF markup or links."""
            return Paragraph(escape(text).replace('\n', '<br/>'), styles[style])

        def heading(text: str) -> None:
            """Keep section headings with the following paragraph."""
            story.append(paragraph(text, 'ResearchHeading'))

        def claims(items: list[Claim]) -> None:
            """Add source-numbered findings as individual splittable paragraphs."""
            for item in items:
                story.append(paragraph(claim_text(item, refs)))

        story.append(paragraph('MARKET INTELLIGENCE', 'ResearchSmall'))
        story.append(paragraph(f'{briefing.company}\nCompetitor analysis briefing', 'ResearchTitle'))
        story.append(paragraph(f'As of {briefing.generated_at[:10]} UTC | Run {briefing.run_id}', 'ResearchSmall'))
        if briefing.demo:
            story.append(paragraph('SYNTHETIC DEMO - NOT REAL MARKET RESEARCH', 'ResearchHeading'))
        story.append(HRFlowable(width='100%', color=TEAL, thickness=2, spaceAfter=12))
        story.append(paragraph('Market scope: ' + briefing.market_scope))
        heading('Executive briefing')
        claims(briefing.synthesis.executive_summary)
        heading('Comparison at a glance')
        rows = [[paragraph(text, 'ResearchSmall') for text in ('Company', 'Pricing', 'Core features', 'Positioning')]]
        for profile in [briefing.target, *briefing.competitors]:
            cells = [profile.company]
            for category in (profile.pricing, profile.features, profile.positioning):
                item = category[0]
                if len(item.text) > 125:
                    item = item.model_copy(update={'text': item.text[:122] + '...'})
                cells.append(claim_text(item, refs))
            rows.append([paragraph(text, 'ResearchSmall') for text in cells])
        table = Table(rows, colWidths=[104, 125, 145, 125], repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E6F1F4')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 7),
            ('RIGHTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LINEBELOW', (0, 0), (-1, -1), 0.4, colors.HexColor('#D5DEE6'))]))
        story.append(table)
        heading('Why these competitors')
        for competitor in briefing.discovery.competitors:
            story.append(paragraph(f'{competitor.name}: {claim_text(competitor.rationale, refs)}'))
        for profile in [briefing.target, *briefing.competitors]:
            start = len(story)
            heading(profile.company)
            for label, items in [('Pricing', profile.pricing), ('Core features', profile.features),
                                 ('Market positioning', profile.positioning), ('Recent news', profile.news)]:
                story.append(paragraph(label, 'ResearchLabel'))
                claims(items)
            for gap in profile.gaps:
                story.append(paragraph('Gap: ' + gap, 'ResearchSmall'))
            block = story[start:]
            del story[start:]
            story.append(KeepTogether(block))
        for label, items in [('Opportunities', briefing.synthesis.opportunities), ('Risks', briefing.synthesis.risks)]:
            heading(label)
            claims(items)
        heading('Limitations and collection notes')
        for note in [*briefing.synthesis.limitations, *briefing.warnings]:
            story.append(paragraph(note))
        heading('Source register')
        for source in briefing.sources:
            story.append(paragraph(f'[{refs[source.id]}] {source.title}', 'ResearchSmall'))
            story.append(Paragraph(f'<link href="{escape(source.url, {chr(34): "&quot;"})}" color="#087F8C">{escape(source.url)}</link>', styles['ResearchSmall']))
            story.append(paragraph(f'Published: {source.published_at or "not supplied"} | Retrieved: {source.retrieved_at}', 'ResearchSmall'))
        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=48, leftMargin=48,
            topMargin=42, bottomMargin=46, title=f'{briefing.company} competitor analysis', author='comparison_app Research Agents')

        def footer(canvas, doc) -> None:
            """Draw unobtrusive running page numbers within reserved margins."""
            canvas.saveState()
            canvas.setFont('ResearchBody', 7)
            canvas.setFillColor(NAVY)
            canvas.drawString(48, 25, 'comparison_app | Market research briefing')
            canvas.drawRightString(A4[0] - 48, 25, f'Page {doc.page}')
            canvas.restoreState()

        document.build(story, onFirstPage=footer, onLaterPages=footer)
        log.info('PDF briefing generated (%d bytes).', buffer.tell())
        return buffer.getvalue()
    except Exception as pdf_error:
        raise ResearchError('PDF export failed. Check configured fonts and report layout.') from pdf_error

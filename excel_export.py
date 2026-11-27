"""Small Excel OOXML exporter using the Python standard library.

All input is written as literal text (except Score), never as Excel formulae.
The ZIP package is built to a temporary path then atomically replaced.
"""
from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


def _xml(value):
    text = str(value if value is not None else '')
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\t\n\r')
    return escape(text, {'"':'&quot;', "'":'&apos;'})


def _col_name(n):
    s = ''
    while n:
        n, r = divmod(n-1, 26)
        s = chr(65 + r) + s
    return s


def _sheet(columns, rows):
    letters = [_col_name(i+1) for i in range(len(columns))]
    end = f'{letters[-1]}{max(2,len(rows)+1)}'
    yield '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    yield '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    yield '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
    yield '<sheetFormatPr defaultRowHeight="17"/>'
    yield '<cols>'
    for i, name in enumerate(columns, 1):
        width = 38 if name in ('Business Name','Website Pages Checked','OSM Listing','Review Notes') else 31 if name in ('Business Email','Website') else 22
        yield f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>'
    yield '</cols><sheetData>'
    yield '<row r="1" ht="26" customHeight="1">'
    for idx, name in enumerate(columns):
        yield f'<c r="{letters[idx]}1" s="1" t="inlineStr"><is><t>{_xml(name)}</t></is></c>'
    yield '</row>'
    for row_num, row in enumerate(rows, 2):
        yield f'<row r="{row_num}">'
        for idx, key in enumerate(columns):
            value = row.get(key, '')
            loc = f'{letters[idx]}{row_num}'
            if key == 'Score' and isinstance(value, (int, float)):
                yield f'<c r="{loc}" t="n"><v>{value}</v></c>'
            else:
                # inlineStr ensures values such as '+4420...' and '=...' cannot run as formulas.
                yield f'<c r="{loc}" t="inlineStr"><is><t xml:space="preserve">{_xml(value)}</t></is></c>'
        yield '</row>'
    yield '</sheetData>'
    yield f'<autoFilter ref="A1:{end}"/>'
    yield '</worksheet>'


def write_xlsx(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr('[Content_Types].xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>''')
            z.writestr('_rels/.rels', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''')
            z.writestr('xl/workbook.xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Partnership Leads" sheetId="1" r:id="rId1"/></sheets>
</workbook>''')
            z.writestr('xl/_rels/workbook.xml.rels', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>''')
            z.writestr('xl/styles.xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="10"/><name val="Aptos"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Aptos"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF182E4D"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>''')
            z.writestr('xl/worksheets/sheet1.xml', ''.join(_sheet(columns, rows)))
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()

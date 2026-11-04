"""Relatorio Excel completo de entradas e saidas, montado a partir dos XMLs do mes."""
import os, re
import xml.etree.ElementTree as ET
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import gerar_sintegra

N = '{http://www.portalfiscal.inf.br/nfe}'
FONTE = 'Arial'
AZUL_ESCURO, VERMELHO, CINZA = '1F2A44', 'E1251B', 'F2F4F7'
MOEDA = '#,##0.00;-#,##0.00;"-"'
QTD = '#,##0.000;-#,##0.000;"-"'


# ---------------- leitura dos XMLs ----------------
def _t(el, cam, padrao=''):
    if el is None:
        return padrao
    x = el.find(cam.replace('n:', N))
    return x.text if x is not None and x.text is not None else padrao


def _f(el, cam):
    try:
        return float(_t(el, cam, '0') or 0)
    except ValueError:
        return 0.0


def _dt(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        try:
            return datetime.strptime(s[:10], '%Y-%m-%d')
        except ValueError:
            return None


def _ler_nota(caminho):
    raiz = ET.parse(caminho).getroot()
    inf = raiz.find(f'.//{N}infNFe')
    prot = raiz.find(f'.//{N}protNFe/{N}infProt')
    ide, emit, dest = inf.find(N + 'ide'), inf.find(N + 'emit'), inf.find(N + 'dest')
    tot = inf.find(f'{N}total/{N}ICMSTot')
    itens = []
    for det in inf.findall(N + 'det'):
        prod, imp = det.find(N + 'prod'), det.find(N + 'imposto')
        icms_grp = imp.find(N + 'ICMS') if imp is not None else None
        ic = list(icms_grp)[0] if icms_grp is not None and len(icms_grp) else None
        cst = _t(ic, 'n:CST')
        cst = (_t(ic, 'n:orig', '0') + cst) if cst else _t(ic, 'n:CSOSN')
        ipi = imp.find(f'{N}IPI/{N}IPITrib') if imp is not None else None
        itens.append(dict(
            n=int(det.get('nItem', '0')), cod=_t(prod, 'n:cProd'), desc=_t(prod, 'n:xProd'), ncm=_t(prod, 'n:NCM'),
            cfop=_t(prod, 'n:CFOP'), cst=cst, un=_t(prod, 'n:uCom'), q=_f(prod, 'n:qCom'), vun=_f(prod, 'n:vUnCom'),
            vprod=_f(prod, 'n:vProd'), vdesc=_f(prod, 'n:vDesc'), vbc=_f(ic, 'n:vBC'), picms=_f(ic, 'n:pICMS'),
            vicms=_f(ic, 'n:vICMS'), vbcst=_f(ic, 'n:vBCST'), vst=_f(ic, 'n:vICMSST'), vipi=_f(ipi, 'n:vIPI')))
    doc_emit = _t(emit, 'n:CNPJ') or _t(emit, 'n:CPF')
    doc_dest = _t(dest, 'n:CNPJ') or _t(dest, 'n:CPF') if dest is not None else ''
    return dict(
        chave=(inf.get('Id') or '')[3:], mod=_t(ide, 'n:mod'), num=int(_t(ide, 'n:nNF', '0')),
        serie=_t(ide, 'n:serie'), emissao=_dt(_t(ide, 'n:dhEmi') or _t(ide, 'n:dEmi')), natop=_t(ide, 'n:natOp'),
        emit_nome=_t(emit, 'n:xNome'), emit_doc=doc_emit, emit_uf=_t(emit, 'n:enderEmit/n:UF'),
        dest_nome=_t(dest, 'n:xNome') if dest is not None else '', dest_doc=doc_dest,
        vprod=_f(tot, 'n:vProd'), vfrete=_f(tot, 'n:vFrete'), vseg=_f(tot, 'n:vSeg'), vdesc=_f(tot, 'n:vDesc'),
        voutro=_f(tot, 'n:vOutro'), vipi=_f(tot, 'n:vIPI'), vbc=_f(tot, 'n:vBC'), vicms=_f(tot, 'n:vICMS'),
        vbcst=_f(tot, 'n:vBCST'), vst=_f(tot, 'n:vST'), vnf=_f(tot, 'n:vNF'),
        protocolo=_t(prot, 'n:nProt'), itens=itens)


def _ler_cancelamento(caminho):
    raiz = ET.parse(caminho).getroot()
    inf = raiz.find(f'.//{N}retEvento/{N}infEvento')
    return _dt(_t(inf, 'n:dhRegEvento')), _t(inf, 'n:nProt')


def _mes(nota, periodo):
    return nota['emissao'] is not None and nota['emissao'].strftime('%Y-%m') == periodo


def coletar(xmldir, periodo):
    entradas, saidas = [], []
    pe = os.path.join(xmldir, 'entradas')
    for n in sorted(os.listdir(pe)):
        nota = _ler_nota(os.path.join(pe, n))
        if _mes(nota, periodo):
            entradas.append(nota)
    for sub in ('autorizadas', 'canceladas'):
        ps = os.path.join(xmldir, 'saidas', sub)
        for n in sorted(os.listdir(ps)):
            if not n.endswith('-nfe.xml'):
                continue
            nota = _ler_nota(os.path.join(ps, n))
            if not _mes(nota, periodo):
                continue
            nota['situacao'] = 'Cancelada' if sub == 'canceladas' else 'Autorizada'
            ev = os.path.join(ps, n.replace('-nfe.xml', '-can.xml'))
            nota['canc_dh'], nota['canc_prot'] = _ler_cancelamento(ev) if os.path.isfile(ev) else (None, '')
            saidas.append(nota)
    entradas.sort(key=lambda d: (d['emissao'], d['num']))
    saidas.sort(key=lambda d: (d['mod'] != '65', d['emissao'], d['num']))
    return entradas, saidas


# ---------------- planilha ----------------
FINA = Side(style='thin', color='D0D5DD')


def _cabecalho(ws, titulo, subtitulo, colunas, larguras):
    ws['A1'] = titulo
    ws['A1'].font = Font(name=FONTE, size=14, bold=True, color=VERMELHO)
    ws['A2'] = subtitulo
    ws['A2'].font = Font(name=FONTE, size=10, color='555555')
    for i, (nome, larg) in enumerate(zip(colunas, larguras), start=1):
        c = ws.cell(row=4, column=i, value=nome)
        c.font = Font(name=FONTE, size=10, bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor=AZUL_ESCURO)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = larg
    ws.row_dimensions[4].height = 30
    ws.freeze_panes = 'A5'


def _linhas(ws, linhas, formatos):
    """Escreve linhas a partir da 5; formatos: lista (por coluna) de number_format ou None."""
    fonte = Font(name=FONTE, size=10)
    for r, linha in enumerate(linhas, start=5):
        for c, v in enumerate(linha, start=1):
            cel = ws.cell(row=r, column=c, value=v)
            cel.font = fonte
            if formatos[c - 1]:
                cel.number_format = formatos[c - 1]
    ultima = max(5, 4 + len(linhas))
    ws.auto_filter.ref = f'A4:{get_column_letter(len(formatos))}{ultima}'
    return ultima


def _total(ws, ultima, colunas_soma, ncols, rotulo_col=1):
    tr = ultima + 1
    ws.cell(row=tr, column=rotulo_col, value='TOTAL').font = Font(name=FONTE, size=10, bold=True)
    for c in range(1, ncols + 1):
        cel = ws.cell(row=tr, column=c)
        cel.fill = PatternFill('solid', fgColor=CINZA)
        cel.border = Border(top=Side(style='medium', color=AZUL_ESCURO))
        if c in colunas_soma:
            L = get_column_letter(c)
            cel.value = f'=SUBTOTAL(9,{L}5:{L}{ultima})'
            cel.number_format = MOEDA
            cel.font = Font(name=FONTE, size=10, bold=True)
    return tr


def _doc(d):
    d = re.sub(r'\D', '', d or '')
    if len(d) == 14:
        return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}'
    if len(d) == 11:
        return f'{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}'
    return d


def gerar_excel(xmldir, periodo, lancamento, empresa, destino):
    entradas, saidas = coletar(xmldir, periodo)
    mm, aaaa = periodo[5:], periodo[:4]
    sub = f'{empresa.get("razao", "")}  ·  CNPJ {_doc(empresa.get("cnpj", ""))}  ·  Período {mm}/{aaaa}'
    wb = Workbook()
    wb.calculation.fullCalcOnLoad = True
    ws_res = wb.active
    ws_res.title = 'Resumo'

    # ---- Entradas
    ws = wb.create_sheet('Entradas')
    cols = ['Emissão', 'Lançamento no PDV+', 'Número', 'Série', 'Fornecedor', 'CNPJ/CPF', 'UF', 'Natureza da operação',
            'Valor dos produtos', 'Frete', 'Seguro', 'Desconto', 'Outras despesas', 'IPI', 'Base ICMS', 'ICMS',
            'Base ICMS ST', 'ICMS ST', 'Valor total da nota', 'CFOPs', 'Chave de acesso']
    _cabecalho(ws, 'NF-e de entrada', sub, cols,
               [11, 13, 11, 6, 38, 20, 5, 32, 14, 11, 10, 11, 11, 11, 13, 12, 13, 12, 15, 14, 47])
    linhas = []
    for d in entradas:
        lanc = _dt((lancamento.get(d['chave']) or '').replace(' ', 'T'))
        cfops = ', '.join(sorted({i['cfop'] for i in d['itens']}))
        linhas.append([d['emissao'], lanc, d['num'], d['serie'], d['emit_nome'], _doc(d['emit_doc']), d['emit_uf'],
                       d['natop'], d['vprod'], d['vfrete'], d['vseg'], d['vdesc'], d['voutro'], d['vipi'], d['vbc'],
                       d['vicms'], d['vbcst'], d['vst'], d['vnf'], cfops, d['chave']])
    fm = ['dd/mm/yyyy', 'dd/mm/yyyy', '0', None, None, None, None, None] + [MOEDA] * 11 + [None, '@']
    ult_e = _linhas(ws, linhas, fm)
    _total(ws, ult_e, range(9, 20), len(cols))

    # ---- Itens de entrada
    ws = wb.create_sheet('Itens Entradas')
    cols = ['Emissão', 'Número', 'Fornecedor', 'Item', 'Código', 'Descrição', 'NCM', 'CFOP do fornecedor',
            'CFOP de entrada (SINTEGRA)', 'CST/CSOSN', 'Unid.', 'Quantidade', 'Valor unitário', 'Valor do produto',
            'Desconto', 'Base ICMS', 'Alíquota ICMS (%)', 'ICMS', 'Base ICMS ST', 'ICMS ST', 'IPI']
    _cabecalho(ws, 'Itens das NF-e de entrada', sub, cols,
               [11, 11, 30, 6, 15, 42, 11, 12, 13, 10, 7, 12, 13, 14, 11, 13, 11, 12, 13, 12, 11])
    linhas = []
    for d in entradas:
        for i in d['itens']:
            linhas.append([d['emissao'], d['num'], d['emit_nome'], i['n'], i['cod'], i['desc'], i['ncm'], i['cfop'],
                           gerar_sintegra.cfop_entrada(i['cfop'], {}, set()), i['cst'], i['un'], i['q'], i['vun'],
                           i['vprod'], i['vdesc'], i['vbc'], i['picms'], i['vicms'], i['vbcst'], i['vst'], i['vipi']])
    fm = ['dd/mm/yyyy', '0', None, '0', '@', None, '@', '@', '@', '@', None, QTD, '#,##0.0000', MOEDA, MOEDA, MOEDA,
          '0.00', MOEDA, MOEDA, MOEDA, MOEDA]
    ult_ie = _linhas(ws, linhas, fm)
    _total(ws, ult_ie, [14, 15, 16, 18, 19, 20, 21], len(cols))

    # ---- Saidas
    ws = wb.create_sheet('Saídas')
    cols = ['Modelo', 'Número', 'Série', 'Emissão', 'Situação', 'Destinatário', 'CPF/CNPJ', 'Valor dos produtos',
            'Desconto', 'Outras despesas', 'Valor total', 'Base ICMS', 'ICMS', 'Protocolo de autorização',
            'Data do cancelamento', 'Protocolo do cancelamento', 'Chave de acesso']
    _cabecalho(ws, 'Saídas: NFC-e e NF-e (autorizadas e canceladas)', sub, cols,
               [8, 9, 6, 16, 12, 32, 20, 14, 11, 11, 13, 12, 11, 18, 16, 18, 47])
    linhas = []
    for d in saidas:
        linhas.append(['NFC-e' if d['mod'] == '65' else 'NF-e', d['num'], d['serie'], d['emissao'], d['situacao'],
                       d['dest_nome'] or ('Consumidor final' if d['mod'] == '65' else ''), _doc(d['dest_doc']),
                       d['vprod'], d['vdesc'], d['voutro'], d['vnf'], d['vbc'], d['vicms'], d['protocolo'],
                       d['canc_dh'], d['canc_prot'], d['chave']])
    fm = [None, '0', None, 'dd/mm/yyyy hh:mm', None, None, None, MOEDA, MOEDA, MOEDA, MOEDA, MOEDA, MOEDA, '@',
          'dd/mm/yyyy hh:mm', '@', '@']
    ult_s = _linhas(ws, linhas, fm)
    for r in range(5, 5 + len(linhas)):
        if ws.cell(row=r, column=5).value == 'Cancelada':
            for c in range(1, len(cols) + 1):
                ws.cell(row=r, column=c).font = Font(name=FONTE, size=10, color='C0392B', strike=False)
    _total(ws, ult_s, [8, 9, 10, 11, 12, 13], len(cols))
    ws.cell(row=ult_s + 2, column=1, value='O TOTAL soma as linhas visíveis no filtro, inclusive canceladas. '
            'Para o total válido, filtre Situação = Autorizada (ou veja a aba Resumo).').font = \
        Font(name=FONTE, size=9, italic=True, color='555555')

    # ---- Itens de saida
    ws = wb.create_sheet('Itens Saídas')
    cols = ['Modelo', 'Número', 'Emissão', 'Situação', 'Item', 'Código', 'Descrição', 'NCM', 'CFOP', 'CST/CSOSN',
            'Unid.', 'Quantidade', 'Valor unitário', 'Valor do produto', 'Desconto', 'Valor líquido', 'Base ICMS', 'ICMS']
    _cabecalho(ws, 'Itens das saídas (NFC-e e NF-e)', sub, cols,
               [8, 9, 16, 12, 6, 15, 42, 11, 8, 10, 7, 12, 13, 14, 11, 13, 12, 11])
    linhas = []
    for d in saidas:
        for i in d['itens']:
            linhas.append(['NFC-e' if d['mod'] == '65' else 'NF-e', d['num'], d['emissao'], d['situacao'], i['n'],
                           i['cod'], i['desc'], i['ncm'], i['cfop'], i['cst'], i['un'], i['q'], i['vun'], i['vprod'],
                           i['vdesc'], None, i['vbc'], i['vicms']])
    fm = [None, '0', 'dd/mm/yyyy hh:mm', None, '0', '@', None, '@', '@', '@', None, QTD, '#,##0.0000', MOEDA, MOEDA,
          MOEDA, MOEDA, MOEDA]
    ult_is = _linhas(ws, linhas, fm)
    for r in range(5, 5 + len(linhas)):
        ws.cell(row=r, column=16, value=f'=N{r}-O{r}')
    _total(ws, ult_is, [14, 15, 16, 17, 18], len(cols))

    _resumo(ws_res, sub, mm, aaaa, entradas, saidas, ult_e, ult_ie, ult_s, ult_is)
    wb.save(destino)
    return destino


def _resumo(ws, sub, mm, aaaa, entradas, saidas, ult_e, ult_ie, ult_s, ult_is):
    ws['A1'] = f'Relatório de entradas e saídas · {mm}/{aaaa}'
    ws['A1'].font = Font(name=FONTE, size=16, bold=True, color=VERMELHO)
    ws['A2'] = sub
    ws['A2'].font = Font(name=FONTE, size=10, color='555555')
    ws['A3'] = f'Gerado pelo Aliber SINTEGRA em {datetime.now():%d/%m/%Y %H:%M}. Valores extraídos dos XMLs das notas.'
    ws['A3'].font = Font(name=FONTE, size=9, italic=True, color='777777')
    for col, larg in zip('ABCDE', [34, 14, 18, 16, 16]):
        ws.column_dimensions[col].width = larg
    negrito, normal = Font(name=FONTE, size=10, bold=True), Font(name=FONTE, size=10)

    def cab(linha, titulos):
        for i, t in enumerate(titulos, start=1):
            c = ws.cell(row=linha, column=i, value=t)
            c.font = Font(name=FONTE, size=10, bold=True, color='FFFFFF')
            c.fill = PatternFill('solid', fgColor=AZUL_ESCURO)
            c.alignment = Alignment(horizontal='center' if i > 1 else 'left')

    def secao(linha, texto):
        ws.cell(row=linha, column=1, value=texto).font = Font(name=FONTE, size=12, bold=True, color=AZUL_ESCURO)

    E, S, IE, IS = "'Entradas'", "'Saídas'", "'Itens Entradas'", "'Itens Saídas'"
    sa = lambda col: f'{S}!${col}$5:${col}${ult_s}'

    secao(5, 'Totais do mês')
    cab(6, ['Documento', 'Quantidade', 'Valor total (R$)', 'ICMS (R$)'])
    linhas = [
        ('NF-e de entrada', f'=COUNT({E}!$C$5:$C${ult_e})', f'=SUM({E}!$S$5:$S${ult_e})', f'=SUM({E}!$P$5:$P${ult_e})'),
    ]
    for mod, rot in (('NFC-e', 'NFC-e'), ('NF-e', 'NF-e de saída')):
        for sit, rs_ in (('Autorizada', 'autorizadas'), ('Cancelada', 'canceladas')):
            linhas.append((f'{rot} {rs_}',
                           f'=COUNTIFS({sa("A")},"{mod}",{sa("E")},"{sit}")',
                           f'=SUMIFS({sa("K")},{sa("A")},"{mod}",{sa("E")},"{sit}")',
                           f'=SUMIFS({sa("M")},{sa("A")},"{mod}",{sa("E")},"{sit}")'))
    for k, (rot, q, v, ic) in enumerate(linhas, start=7):
        ws.cell(row=k, column=1, value=rot).font = normal
        for c, f in ((2, q), (3, v), (4, ic)):
            cel = ws.cell(row=k, column=c, value=f)
            cel.font = normal
            cel.number_format = '0' if c == 2 else MOEDA
    # 7 entrada | 8 NFC-e aut | 9 NFC-e canc | 10 NF-e aut | 11 NF-e canc
    k = 12
    ws.cell(row=k, column=1, value='Total de saídas autorizadas').font = negrito
    for c, L in ((2, 'B'), (3, 'C'), (4, 'D')):
        cel = ws.cell(row=k, column=c, value=f'={L}8+{L}10')
        cel.font = negrito
        cel.number_format = '0' if c == 2 else MOEDA
        cel.fill = PatternFill('solid', fgColor=CINZA)
    ws.cell(row=k, column=1).fill = PatternFill('solid', fgColor=CINZA)

    # Entradas por CFOP
    linha = 14
    secao(linha, 'Entradas por CFOP (CFOP de entrada, como no SINTEGRA)')
    cab(linha + 1, ['CFOP', 'Itens', 'Valor dos produtos (R$)', 'Base ICMS (R$)', 'ICMS (R$)'])
    cf_ent = sorted({gerar_sintegra.cfop_entrada(i['cfop'], {}, set()) for d in entradas for i in d['itens']})
    ie = lambda col: f'{IE}!${col}$5:${col}${ult_ie}'
    r = linha + 2
    ini = r
    for cf in cf_ent:
        ws.cell(row=r, column=1, value=cf).font = normal
        ws.cell(row=r, column=2, value=f'=COUNTIFS({ie("I")},A{r})').number_format = '0'
        ws.cell(row=r, column=3, value=f'=SUMIFS({ie("N")},{ie("I")},A{r})').number_format = MOEDA
        ws.cell(row=r, column=4, value=f'=SUMIFS({ie("P")},{ie("I")},A{r})').number_format = MOEDA
        ws.cell(row=r, column=5, value=f'=SUMIFS({ie("R")},{ie("I")},A{r})').number_format = MOEDA
        for c in range(2, 6):
            ws.cell(row=r, column=c).font = normal
        r += 1
    if r == ini:
        ws.cell(row=r, column=1, value='(sem entradas no mês)').font = normal
        r += 1

    # Saidas por CFOP (so autorizadas)
    linha = r + 1
    secao(linha, 'Saídas autorizadas por CFOP (canceladas não entram)')
    cab(linha + 1, ['CFOP', 'Itens', 'Valor líquido (R$)', 'Base ICMS (R$)', 'ICMS (R$)'])
    cf_sai = sorted({i['cfop'] for d in saidas if d['situacao'] == 'Autorizada' for i in d['itens']})
    is_ = lambda col: f'{IS}!${col}$5:${col}${ult_is}'
    r = linha + 2
    ini = r
    for cf in cf_sai:
        crit = f'{is_("I")},A{r},{is_("D")},"Autorizada"'
        ws.cell(row=r, column=1, value=cf).font = normal
        ws.cell(row=r, column=2, value=f'=COUNTIFS({crit})').number_format = '0'
        ws.cell(row=r, column=3, value=f'=SUMIFS({is_("P")},{crit})').number_format = MOEDA
        ws.cell(row=r, column=4, value=f'=SUMIFS({is_("Q")},{crit})').number_format = MOEDA
        ws.cell(row=r, column=5, value=f'=SUMIFS({is_("R")},{crit})').number_format = MOEDA
        for c in range(2, 6):
            ws.cell(row=r, column=c).font = normal
        r += 1
    if r == ini:
        ws.cell(row=r, column=1, value='(sem saídas autorizadas no mês)').font = normal
        r += 1
    ws.cell(row=r + 1, column=1, value='Abas: Entradas, Itens Entradas, Saídas e Itens Saídas trazem o detalhe nota a '
            'nota e item a item, com filtro. Canceladas aparecem em vermelho na aba Saídas.').font = \
        Font(name=FONTE, size=9, italic=True, color='555555')
    ws.sheet_view.showGridLines = False

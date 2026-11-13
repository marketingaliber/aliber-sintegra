#!/usr/bin/env python3
"""Gera o arquivo SINTEGRA (Convenio ICMS 57/95) a partir de XMLs de NF-e (55) e NFC-e (65).

Registros gerados: 10, 11, 50, 53, 54, 61, 61R, 75, 88, 90.
Uso rapido:
  python3 gerar_sintegra.py --entradas ENTRADAS.zip --saidas SAIDAS.zip --periodo 2026-09 \
      --telefone 32999949440 [--db backup_pdv.db] [--saida-dir /mnt/user-data/outputs]
Veja --help e ../SKILL.md.
"""
import argparse, calendar, collections, glob, json, os, re, shutil, sqlite3, sys, tempfile, unicodedata, zipfile
import xml.etree.ElementTree as ET

NS = {'n': 'http://www.portalfiscal.inf.br/nfe'}

# ---------------------------------------------------------------- utilitarios
def T(r, x, d=None):
    if r is None: return d
    e = r.find(x, NS)
    return e.text if e is not None and e.text is not None else d

def F(r, x):
    try: return float(T(r, x, '0') or 0)
    except ValueError: return 0.0

def ascii_(s):
    return unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().upper()

def tx(s, w): return ascii_(s)[:w].ljust(w)
def nm(v, w, dec=2): return str(int(round(abs(v) * 10 ** dec))).zfill(w)[-w:]
def dig(s, w): return re.sub(r'\D', '', s or '').zfill(w)[-w:]
def ymd(iso): return iso[:10].replace('-', '')

def gtin_ok(e):
    if not e or not e.isdigit() or len(e) not in (8, 12, 13, 14) or int(e) == 0: return False
    d = [int(x) for x in e]
    t = sum(x * (3 if i % 2 == 0 else 1) for i, x in enumerate(d[:-1][::-1]))
    return (10 - t % 10) % 10 == d[-1]

def mg_ie_ok(ie13):
    """Valida digitos verificadores de IE de MG (13 digitos)."""
    if not re.fullmatch(r'\d{13}', ie13): return False
    d = ie13[:11]; s = d[:3] + '0' + d[3:]; tot = 0
    for i, ch in enumerate(s):
        p = int(ch) * (1 if i % 2 == 0 else 2); tot += p // 10 + p % 10
    d1 = (10 - tot % 10) % 10
    w = [3, 2, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2]
    t = sum(int(c) * x for c, x in zip(d + str(d1), w)); d2 = 11 - t % 11
    return ie13 == d + str(d1) + str(0 if d2 >= 10 else d2)

# ---------------------------------------------------------------- CFOP de entrada
CFOP_ENTRADA = {  # CFOP do fornecedor (saida) -> CFOP de entrada para REVENDA
    '5101': '1102', '5102': '1102', '5103': '1102', '5104': '1102', '5105': '1102', '5106': '1102',
    '6101': '2102', '6102': '2102', '6103': '2102', '6104': '2102', '6105': '2102', '6106': '2102',
    '5401': '1403', '5403': '1403', '5405': '1403', '6401': '2403', '6403': '2403', '6404': '2403', '6405': '2403',
    '5910': '1910', '6910': '2910', '5949': '1949', '6949': '2949',
    '5201': '1202', '5202': '1202', '6201': '2202', '6202': '2202',   # devolucao de compra -> devolucao de venda
    '5551': '1551', '6551': '2551', '5556': '1556', '6556': '2556',
}
def cfop_entrada(c, custom, avisos):
    if c in custom: return custom[c]
    if c in CFOP_ENTRADA: return CFOP_ENTRADA[c]
    if c[0] in '1234567' and c[0] in '123': return c  # ja e CFOP de entrada
    novo = {'5': '1', '6': '2', '7': '3'}.get(c[0], c[0]) + c[1:]
    avisos.add(f'CFOP {c} sem regra especifica; usei {novo} (troca do 1o digito). Confirmar com o contador.')
    return novo

# ---------------------------------------------------------------- leitura dos XMLs
def materializar(origem, tmp):
    """Aceita pasta, .zip ou .rar; devolve lista de caminhos .xml (corrige nomes com barra invertida)."""
    if not origem: return []
    if os.path.isdir(origem):
        base = origem
    else:
        base = tempfile.mkdtemp(dir=tmp)
        if origem.lower().endswith('.zip'):
            with zipfile.ZipFile(origem) as z:
                for i in z.infolist():
                    if i.is_dir(): continue
                    dest = os.path.join(base, i.filename.replace('\\', '/'))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(i) as s, open(dest, 'wb') as o: shutil.copyfileobj(s, o)
        else:
            os.system(f'unrar x -o+ -inul "{origem}" "{base}/" 2>/dev/null || unar -q -o "{base}" "{origem}" >/dev/null 2>&1 || 7z x -y -o"{base}" "{origem}" >/dev/null 2>&1')
    out = []
    for root, _, files in os.walk(base):
        for f in files:
            if f.lower().endswith('.xml'): out.append(os.path.join(root, f))
    # nomes com '\' (zips criados no Windows e extraidos no Linux)
    for p in list(out):
        if '\\' in os.path.basename(p):
            novo = os.path.join(os.path.dirname(p), os.path.basename(p).replace('\\', '/'))
            os.makedirs(os.path.dirname(novo), exist_ok=True); shutil.move(p, novo)
    return sorted(os.path.join(r, f) for r, _, fs in os.walk(base) for f in fs if f.lower().endswith('.xml'))

def itens(inf, avisos=None, rot=''):
    out = []
    for d in inf.findall('n:det', NS):
        p = d.find('n:prod', NS); imp = d.find('n:imposto', NS)
        grp = imp.find('n:ICMS', NS) if imp is not None else None
        ic = grp[0] if grp is not None and len(grp) else None
        if ic is None:
            # item sem grupo de ICMS (ex.: servico tributado pelo ISSQN em nota conjugada): sem ICMS, CST 090 (outras)
            if avisos is not None:
                iss = imp is not None and imp.find('n:ISSQN', NS) is not None
                avisos.add(f'{rot}: item {d.get("nItem")} ({T(p, "n:xProd", "")[:40]}) sem ICMS no XML'
                           f'{" (servico com ISSQN)" if iss else ""}; lancado sem ICMS, CST 090.')
        cst = T(ic, 'n:CST'); csosn = T(ic, 'n:CSOSN')
        if ic is None: cst = '90'
        ipi = imp.find('n:IPI/n:IPITrib', NS) if imp is not None else None
        out.append(dict(n=int(d.get('nItem')), cod=T(p, 'n:cProd'), desc=T(p, 'n:xProd'), ncm=T(p, 'n:NCM'),
            un=T(p, 'n:uCom'), ean=[T(p, 'n:cEAN'), T(p, 'n:cEANTrib')], cfop=T(p, 'n:CFOP'),
            q=F(p, 'n:qCom'), vprod=F(p, 'n:vProd'), vdesc=F(p, 'n:vDesc'), vfrete=F(p, 'n:vFrete'),
            vseg=F(p, 'n:vSeg'), voutro=F(p, 'n:vOutro'), vipi=F(ipi, 'n:vIPI') if ipi is not None else 0.0,
            cst=(T(ic, 'n:orig', '0') + cst) if cst else (csosn or '000'), vbc=F(ic, 'n:vBC'), picms=F(ic, 'n:pICMS'),
            vicms=F(ic, 'n:vICMS'), vbcst=F(ic, 'n:vBCST'), vst=F(ic, 'n:vICMSST')))
    return out

def total_item(i):
    return i['vprod'] - i['vdesc'] + i['vfrete'] + i['vseg'] + i['voutro'] + i['vipi'] + i['vst']

def carregar(paths, rotulo, avisos, canc_chaves):
    """Devolve dict chave -> info. Registra eventos de cancelamento em canc_chaves."""
    docs = {}
    for p in paths:
        try: r = ET.parse(p).getroot()
        except ET.ParseError: avisos.add(f'{os.path.basename(p)}: XML invalido, ignorado.'); continue
        tag = r.tag.split('}')[-1]
        if tag == 'procEventoNFe':
            if T(r, './/n:infEvento/n:tpEvento') == '110111' and T(r, './/n:retEvento/n:infEvento/n:cStat', '135') in ('135', '155'):
                canc_chaves.add(T(r, './/n:infEvento/n:chNFe'))
            continue
        inf = r.find('.//n:infNFe', NS)
        if inf is None: continue
        chave = inf.get('Id', '')[3:]
        mod = T(inf, 'n:ide/n:mod')
        if mod not in ('55', '65'):
            avisos.add(f'{os.path.basename(p)}: modelo {mod} nao suportado, ignorado.'); continue
        cstat = T(r, './/n:protNFe/n:infProt/n:cStat')
        cancel_path = 'cancel' in p.lower()
        docs[chave] = dict(chave=chave, inf=inf, mod=mod, cstat=cstat, path=p, cancel_path=cancel_path, origem=rotulo)
    return docs

# ---------------------------------------------------------------- PDV+ (opcional)
class PDV:
    """Cadastro de produtos do backup SQLite do PDV+ (codigo, descricao, NCM, unidade, EAN)."""
    def __init__(self, caminho):
        self.db = sqlite3.connect(f'file:{caminho}?mode=ro', uri=True)
        self.prod = {}
        for pid, cod, desc, ncm, un in self.db.execute(
                "select p.id_produto,p.codigo_produto,p.descricao,p.ncm,coalesce(u.descricao,'UN') "
                "from produto p left join prod_unidade u on u.id_prod_unidade=p.id_prod_unidade"):
            self.prod[pid] = dict(cod=str(cod), desc=(desc or '').strip(), ncm=ncm or '', un=un, eans=set())
        for pid, cb in self.db.execute("select id_produto,codigo_barra from prod_cod_barras where data_hora_deletado is null"):
            if pid in self.prod and gtin_ok(cb or ''): self.prod[pid]['eans'].add(cb)
        self.bycod = {v['cod']: v for v in self.prod.values()}
        self.item = {}      # (chave, nItem) -> id_produto
        self.data_entrada = {}  # chave -> data de lancamento da entrada
        for ch, n, pid, dh in self.db.execute(
                "select n.chave_acesso,i.numero_item_nota_fiscal,i.id_produto,e.data_hora from nota_fiscal_compra n "
                "join entrada e on e.id_nota_fiscal_compra=n.id_nota_fiscal_compra "
                "join entrada_item i on i.id_entrada=e.id_entrada where e.data_hora_deletado is null"):
            self.item[(ch, str(int(n)))] = pid; self.data_entrada[ch] = dh[:10].replace('-', '')
        self.canceladas = {r[0] for r in self.db.execute("select chave_acesso from nota_fiscal where situacao=3")}
        d = self.db.execute("select razao_social,inscricao_estadual,fone from dados_empresa limit 1").fetchone()
        self.empresa = dict(zip(('razao', 'ie', 'fone'), d)) if d else {}

# ---------------------------------------------------------------- geracao
def gerar(a):
    avisos = set(); info = []
    tmp = tempfile.mkdtemp()
    canc = set()
    ent = carregar(materializar(a.entradas, tmp), 'entrada', avisos, canc)
    sai = carregar(materializar(a.saidas, tmp), 'saida', avisos, canc)
    pdv = PDV(a.db) if a.db else None
    if pdv: canc |= pdv.canceladas
    custom_cfop = json.load(open(a.cfop_json)) if a.cfop_json else {}

    alld = {**ent, **sai}
    # ---- empresa: CNPJ por argumento ou deduzido (emitente das saidas / destinatario das entradas)
    cnpj = dig(a.cnpj, 14) if a.cnpj else None
    if not cnpj:
        c = collections.Counter([T(d['inf'], 'n:emit/n:CNPJ') for d in sai.values()] +
                                [T(d['inf'], 'n:dest/n:CNPJ') for d in ent.values()])
        cnpj = c.most_common(1)[0][0]; info.append(f'CNPJ deduzido dos XMLs: {cnpj}')
    emp_inf = None
    for d in list(sai.values()) + list(ent.values()):
        if T(d['inf'], 'n:emit/n:CNPJ') == cnpj: emp_inf = d['inf'].find('n:emit', NS); break
    if emp_inf is None:
        for d in ent.values():
            if T(d['inf'], 'n:dest/n:CNPJ') == cnpj: emp_inf = d['inf'].find('n:dest', NS); break
    end = emp_inf.find('n:enderEmit', NS) if emp_inf is not None and emp_inf.find('n:enderEmit', NS) is not None else (emp_inf.find('n:enderDest', NS) if emp_inf is not None else None)
    razao = a.razao or T(emp_inf, 'n:xNome') or (pdv.empresa.get('razao') if pdv else '') or ''
    ie = re.sub(r'\D', '', a.ie or T(emp_inf, 'n:IE') or (pdv.empresa.get('ie') if pdv and pdv.empresa else '') or '')
    uf = a.uf or T(end, 'n:UF') or 'MG'
    if uf == 'MG' and len(ie) < 13 and mg_ie_ok(ie.zfill(13)):
        info.append(f'IE {ie} completada com zeros a esquerda para 13 digitos (digito verificador de MG confere).'); ie = ie.zfill(13)
    elif uf == 'MG' and len(ie) == 13 and not mg_ie_ok(ie):
        avisos.add('IE de MG com digito verificador invalido: conferir a IE informada.')
    emp = dict(cnpj=cnpj, ie=ie, nome=razao, mun=a.municipio or T(end, 'n:xMun') or '', uf=uf,
               lgr=a.logradouro or T(end, 'n:xLgr') or '', nro=a.numero or T(end, 'n:nro') or '0',
               cpl=a.complemento if a.complemento is not None else (T(end, 'n:xCpl') or ''),
               bai=a.bairro or T(end, 'n:xBairro') or '', cep=dig(a.cep or T(end, 'n:CEP'), 8),
               contato=a.contato or razao, tel=dig(a.telefone or T(end, 'n:fone') or '', 12))
    if not (a.telefone or T(end, 'n:fone')): avisos.add('TELEFONE nao informado: registro 11 ficou zerado (o validador aponta erro). Pergunte ao usuario.')

    # ---- periodo
    if a.periodo:
        ano, mes = map(int, a.periodo.split('-'))
    else:
        c = collections.Counter(T(d['inf'], 'n:ide/n:dhEmi')[:7] for d in alld.values())
        ano, mes = map(int, c.most_common(1)[0][0].split('-')); info.append(f'Periodo deduzido: {ano}-{mes:02d}')
    INI = f'{ano}{mes:02d}01'; FIM = f'{ano}{mes:02d}{calendar.monthrange(ano, mes)[1]:02d}'; MESANO = f'{mes:02d}{ano}'

    L50, L53, L54 = [], [], []
    prod = collections.defaultdict(list)
    nfce_ok, nfce_canc, nfce_items = [], [], []
    resumo = collections.Counter(); valores = collections.Counter()

    def data_doc(d, tipo):
        dt = ymd(T(d['inf'], 'n:ide/n:dhEmi'))
        if tipo == 'E' and a.data_entrada == 'lancamento' and pdv and d['chave'] in pdv.data_entrada: dt = pdv.data_entrada[d['chave']]
        return dt

    for chave, d in sorted(alld.items(), key=lambda kv: (T(kv[1]['inf'], 'n:ide/n:dhEmi'), kv[0])):
        inf = d['inf']; ide = inf.find('n:ide', NS); em = inf.find('n:emit', NS); de = inf.find('n:dest', NS)
        num = int(T(ide, 'n:nNF')); ser = T(ide, 'n:serie', '0'); vnf = F(inf, 'n:total/n:ICMSTot/n:vNF')
        emit_cnpj = T(em, 'n:CNPJ'); dest_cnpj = T(de, 'n:CNPJ') or T(de, 'n:CPF')
        rot = f"{'NFC-e' if d['mod']=='65' else 'NF-e'} {num}/{ser}"
        if emit_cnpj == cnpj and T(ide, 'n:tpNF') == '1': tipo = 'S'
        elif dest_cnpj == cnpj and emit_cnpj != cnpj: tipo = 'E'
        else:
            avisos.add(f'{rot} (chave ...{chave[-8:]}): nao pertence ao CNPJ {cnpj} como entrada ou saida; ignorada.'); continue
        if d['cstat'] != '100':
            avisos.add(f'{rot}: protocolo cStat={d["cstat"]} (nao autorizada); ignorada.'); continue
        cancelada = d['cancel_path'] or chave in canc
        dt = data_doc(d, tipo)
        if not (INI <= dt <= FIM):
            avisos.add(f'{rot}: data {dt} fora do periodo {INI}-{FIM}; ignorada.'); continue
        if tipo == 'S' and d['origem'] == 'entrada': avisos.add(f'{rot}: nota de saida da propria empresa encontrada na pasta de entradas; tratada como saida.')
        if tipo == 'E' and d['mod'] == '65': avisos.add(f'{rot}: NFC-e como entrada nao e tratada; ignorada.'); continue
        if tipo == 'E' and cancelada: avisos.add(f'{rot}: entrada cancelada; ignorada.'); continue

        its = itens(inf, avisos, rot)
        if tipo == 'E' and pdv:
            for i in its:
                pid = pdv.item.get((chave, str(i['n'])))
                if pid: i['cod'] = pdv.prod[pid]['cod']
                else: avisos.add(f'{rot}: item {i["n"]} sem vinculo no PDV+; usei o codigo do fornecedor {i["cod"]}.')

        # --- NFC-e -> registros 61/61R
        if d['mod'] == '65':
            if cancelada: nfce_canc.append((dt, num, ser)); resumo['NFC-e cancelada'] += 1; continue
            nfce_ok.append(dict(dt=dt, num=num, ser=ser, its=its)); resumo['NFC-e autorizada'] += 1; valores['NFC-e'] += vnf
            for i in its: nfce_items.append(i); prod[i['cod']].append(i)
            continue

        # --- NF-e 55 -> registros 50/53/54
        cnpj_p = emit_cnpj if tipo == 'E' else dest_cnpj
        ie_p = T(em, 'n:IE', 'ISENTO') if tipo == 'E' else T(de, 'n:IE', 'ISENTO')
        uf_p = T(em, 'n:enderEmit/n:UF') if tipo == 'E' else T(de, 'n:enderDest/n:UF')
        base = '50' + dig(cnpj_p, 14) + tx(ie_p, 14) + dt + tx(uf_p, 2) + '55' + tx(ser, 3) + str(num).zfill(6)[-6:]
        if cancelada:
            L50.append((dt, num, base + '0000P' + nm(0, 13) * 5 + nm(0, 4) + 'S'))
            resumo['NF-e cancelada'] += 1; continue
        for i in its: i['cf'] = cfop_entrada(i['cfop'], custom_cfop, avisos) if tipo == 'E' else i['cfop']
        if abs(sum(total_item(i) for i in its) - vnf) > 0.02:
            avisos.add(f'{rot}: soma dos itens {sum(total_item(i) for i in its):.2f} difere do vNF {vnf:.2f}.')
        if tipo == 'E' and any(i['vipi'] for i in its): avisos.add(f'{rot}: tem IPI; registro 51 (IPI) nao e gerado por este script.')
        g = collections.OrderedDict()
        for i in its: g.setdefault((i['cf'], round(i['picms'], 2)), []).append(i)
        for (cf, al), xs in g.items():
            tot = sum(total_item(i) for i in xs); bc = sum(i['vbc'] for i in xs); ic = sum(i['vicms'] for i in xs)
            isen = sum(total_item(i) for i in xs if i['cst'][1:] in ('40', '41', '50') or i['cst'] in ('300', '400'))
            L50.append((dt, num, base + cf + ('T' if tipo == 'E' else 'P') + nm(tot, 13) + nm(bc, 13) + nm(ic, 13) + nm(isen, 13) + nm(max(tot - bc - isen, 0), 13) + nm(al, 4) + 'N'))
            st = sum(i['vst'] for i in xs)
            if st > 0:
                L53.append((dt, num, '53' + base[2:] + cf + ('T' if tipo == 'E' else 'P') + nm(sum(i['vbcst'] for i in xs), 13) + nm(st, 13) + nm(sum(i['vfrete'] + i['vseg'] + i['voutro'] for i in xs), 13) + 'N' + ' ' * 30))
        for i in its:
            L54.append((dt, num, i['n'], '54' + dig(cnpj_p, 14) + '55' + tx(ser, 3) + str(num).zfill(6)[-6:] + i['cf'] + i['cst'] + str(i['n']).zfill(3) + tx(i['cod'], 14) + nm(i['q'], 11, 3) + nm(i['vprod'], 12) + nm(i['vdesc'], 12) + nm(i['vbc'], 12) + nm(i['vbcst'], 12) + nm(i['vipi'], 12) + nm(i['picms'], 4)))
            prod[i['cod']].append(i)
        resumo[f"NF-e {'entrada' if tipo=='E' else 'saida'}"] += 1; valores[f"NF-e {'entrada' if tipo=='E' else 'saida'}"] += vnf

    # ---- registro 61: por dia e aliquota; faixa de numeracao do dia inclui as canceladas (valor zero)
    L61 = []
    dias = collections.defaultdict(list)
    for n_ in nfce_ok: dias[n_['dt']].append(n_)
    nums_dia = collections.defaultdict(list)
    for n_ in nfce_ok: nums_dia[n_['dt']].append((n_['num'], n_['ser']))
    for dt, num, ser in nfce_canc: nums_dia[dt].append((num, ser))
    for dt in sorted(nums_dia):
        faixa = sorted(nums_dia[dt]); a_, b_, ser = faixa[0][0], faixa[-1][0], faixa[0][1]
        gr = collections.OrderedDict()
        for n_ in dias.get(dt, []):
            for i in n_['its']: gr.setdefault(round(i['picms'], 2), []).append(i)
        if not gr: gr[0.0] = []
        for al, xs in gr.items():
            tot = sum(total_item(i) for i in xs); bc = sum(i['vbc'] for i in xs); ic = sum(i['vicms'] for i in xs)
            isen = sum(total_item(i) for i in xs if i['cst'][1:] in ('40', '41', '50') or i['cst'] in ('300', '400'))
            L61.append('61' + ' ' * 28 + dt + '65' + str(int(ser)).zfill(3) + '  ' + str(a_).zfill(6) + str(b_).zfill(6) + nm(tot, 13) + nm(bc, 13) + nm(ic, 12) + nm(isen, 13) + nm(max(tot - bc - isen, 0), 13) + nm(al, 4) + ' ')
    agg = collections.OrderedDict()
    for i in nfce_items:
        k = (i['cod'], round(i['picms'], 2)); x = agg.setdefault(k, [0.0, 0.0, 0.0]); x[0] += i['q']; x[1] += i['vprod']; x[2] += i['vbc']
    L61R = ['61R' + MESANO + tx(c, 14) + nm(q, 13, 3) + nm(v, 16) + nm(bc, 16) + nm(al, 4) + ' ' * 54 for (c, al), (q, v, bc) in sorted(agg.items(), key=lambda kv: (int(kv[0][0]) if kv[0][0].isdigit() else 0, kv[0][0], kv[0][1]))]

    # ---- 75 / 88
    L75, L88 = [], []
    for cod in sorted(prod, key=lambda x: (int(x) if x.isdigit() else 10 ** 12, x)):
        xs = prod[cod]
        if pdv and cod in pdv.bycod: p = pdv.bycod[cod]; desc, ncm, un, eans = p['desc'], p['ncm'], p['un'], set(p['eans'])
        else:
            desc, ncm, un, eans = xs[0]['desc'], xs[0]['ncm'], xs[0]['un'], set()
            if len({(re.sub(r'[/\-]', ' ', ascii_(x['desc'])), x['ncm']) for x in xs}) > 1:
                avisos.add(f'Codigo {cod} aparece com descricoes/NCM diferentes (codigo de fornecedor colidindo com codigo proprio?). Use --db com o cadastro do PDV+.')
        for x in xs:
            for e in x['ean']:
                if gtin_ok(e): eans.add(e)
        L75.append('75' + INI + FIM + tx(cod, 14) + tx(ncm, 8) + tx(desc, 53) + tx(un, 6) + nm(0, 5) + nm(0, 4) + nm(0, 5) + nm(0, 13))
        for e in sorted(eans, key=lambda e: (len(e), e)):
            L88.append(('88EAN' + str(len(e)).zfill(2) + tx(cod, 14) + tx(desc, 53) + tx(un, 6) + e.ljust(14)).ljust(132))

    # ---- 10 / 11 / 90
    fax = dig(a.fax or '', 10)
    R10 = '10' + emp['cnpj'] + tx(emp['ie'], 14) + tx(emp['nome'], 35) + tx(emp['mun'], 30) + emp['uf'] + fax + INI + FIM + a.convenio + a.natureza + a.finalidade
    # Validador: "Numero ou complemento deve ser preenchido". Endereco sem numero (SN, S/N, KM 690...) -> vai no complemento.
    nro11, cpl11 = dig(emp['nro'], 5), (emp['cpl'] or '').strip()
    if int(nro11) == 0 and not cpl11:
        orig = (emp['nro'] or '').strip()
        cpl11 = orig if re.search(r'[A-Za-z]', orig) else 'SN'
        info.append(f'Endereco sem numero: complemento do registro 11 preenchido com "{cpl11}" (exigencia do validador).')
    R11 = '11' + tx(emp['lgr'], 34) + nro11 + tx(cpl11, 22) + tx(emp['bai'], 15) + emp['cep'] + tx(emp['contato'], 28) + emp['tel']
    l50 = [x[2] for x in sorted(L50, key=lambda x: (x[0], x[1]))]
    l53 = [x[2] for x in sorted(L53, key=lambda x: (x[0], x[1]))]
    l54 = [x[3] for x in sorted(L54, key=lambda x: (x[0], x[1], x[2]))]
    corpo = [R10, R11] + l50 + l53 + l54 + L61 + L61R + L75 + L88
    cnt = collections.OrderedDict((k, v) for k, v in (('50', len(l50)), ('53', len(l53)), ('54', len(l54)), ('61', len(L61) + len(L61R)), ('75', len(L75)), ('88', len(L88))) if v)
    pares = [k + str(v).zfill(8) for k, v in cnt.items()]
    total = len(corpo) + 1
    # a linha 90 comporta 9 pares; o total geral (99) fecha o ultimo. Se passar de 9, abre nova linha 90.
    pares.append('99' + str(total + (0 if len(pares) < 9 else (len(pares) + 1) // 9)).zfill(8))
    chunks = [pares[i:i + 9] for i in range(0, len(pares), 9)]
    cab = '90' + emp['cnpj'] + tx(emp['ie'], 14)
    R90 = [(cab + ''.join(c)).ljust(125) + str(len(chunks)) for c in chunks]
    linhas = corpo + R90

    # ---- autoverificacao
    erros = []
    for i, l in enumerate(linhas):
        esp = 132 if l.startswith('88') else 126
        if len(l) != esp: erros.append(f'linha {i+1} (reg {l[:3]}): tamanho {len(l)} != {esp}')
    c75 = {l[30:44].strip() for l in L75 if False} | {l[18:32].strip() for l in L75}
    for l in l54:
        if l[37:51].strip() not in c75: erros.append(f'registro 54 com codigo {l[37:51].strip()} ausente no 75')
    for l in L61R:
        if l[9:23].strip() not in c75: erros.append(f'registro 61R com codigo {l[9:23].strip()} ausente no 75')
    soma61 = sum(int(l[57:70]) for l in L61) / 100
    if abs(soma61 - valores['NFC-e']) > 0.01: erros.append(f'soma do reg 61 ({soma61:.2f}) difere das NFC-e autorizadas ({valores["NFC-e"]:.2f})')

    os.makedirs(a.saida_dir, exist_ok=True)
    nome = f'SINTEGRA-{cnpj}-{ano}-{mes:02d}.TXT'
    caminho = os.path.join(a.saida_dir, nome)
    with open(caminho, 'w', encoding='ascii', newline='') as f: f.write('\r\n'.join(linhas) + '\r\n')

    print(f'Arquivo: {caminho}  ({len(linhas)} linhas)')
    print(f'Empresa: {emp["nome"].strip()} | CNPJ {cnpj} | IE {emp["ie"]} | {emp["mun"]}/{emp["uf"]} | periodo {INI}-{FIM}')
    print('Registros:', dict(cnt), '| 90:', len(R90), 'linha(s)')
    print('Documentos:', dict(resumo)); print('Valores (autorizados):', {k: round(v, 2) for k, v in valores.items()})
    if nfce_canc: print('NFC-e canceladas (dentro das faixas do reg 61, sem valor):', sorted(nfce_canc))
    for x in info: print('INFO:', x)
    for x in sorted(avisos): print('AVISO:', x)
    for x in erros[:20]: print('ERRO:', x)
    if len(erros) > 20: print(f'ERRO: ... e mais {len(erros) - 20} erros')
    return 1 if erros else 0

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--entradas', help='pasta/.zip/.rar com XMLs de entrada')
    ap.add_argument('--saidas', help='pasta/.zip/.rar com XMLs de saida (NF-e e NFC-e; aceita subpasta de cancelados)')
    ap.add_argument('--periodo', help='AAAA-MM (se omitido, deduz do mes mais frequente)')
    ap.add_argument('--db', help='backup SQLite do PDV+ (codigos de produto, NCM, EAN, cancelamentos)')
    ap.add_argument('--cnpj'); ap.add_argument('--ie'); ap.add_argument('--razao'); ap.add_argument('--uf'); ap.add_argument('--municipio')
    ap.add_argument('--logradouro'); ap.add_argument('--numero'); ap.add_argument('--complemento'); ap.add_argument('--bairro'); ap.add_argument('--cep')
    ap.add_argument('--contato', help='padrao: razao social'); ap.add_argument('--telefone'); ap.add_argument('--fax', help='telefone do reg 10 (10 digitos); padrao zeros')
    ap.add_argument('--convenio', default='3'); ap.add_argument('--natureza', default='3'); ap.add_argument('--finalidade', default='1', help='1=normal, 2=retificacao total, 5=retificacao aditiva')
    ap.add_argument('--data-entrada', choices=['emissao', 'lancamento'], default='emissao', help="data do reg 50 das entradas")
    ap.add_argument('--cfop-json', help='JSON {"6101":"2101"} para sobrescrever a tabela de CFOP de entrada')
    ap.add_argument('--saida-dir', default='.')
    a = ap.parse_args()
    if not (a.entradas or a.saidas): ap.error('informe --entradas e/ou --saidas')
    sys.exit(gerar(a))

if __name__ == '__main__':
    main()

"""Motor do Aliber SINTEGRA: le o banco do PDV+, monta os XMLs e chama o gerador validado."""
import argparse, calendar, contextlib, io, os, re, shutil, sqlite3, struct, tempfile, zipfile, zlib
from datetime import date, timedelta

import gerar_sintegra

NS = 'http://www.portalfiscal.inf.br/nfe'
PASTA_BANCO_PADRAO = r'C:\PDV+\.dart_tool\sqflite_common_ffi\databases'
NOME_BANCO_PADRAO = 'navi_db.db'


def localizar_banco(caminho=None):
    """Devolve o caminho do banco do PDV+ (configurado, padrao ou primeiro .db da pasta padrao)."""
    if caminho and os.path.isfile(caminho):
        return caminho
    padrao = os.path.join(PASTA_BANCO_PADRAO, NOME_BANCO_PADRAO)
    if os.path.isfile(padrao):
        return padrao
    if os.path.isdir(PASTA_BANCO_PADRAO):
        for n in sorted(os.listdir(PASTA_BANCO_PADRAO)):
            if n.lower().endswith('.db'):
                return os.path.join(PASTA_BANCO_PADRAO, n)
    return None


def copiar_banco(origem, destino):
    """Copia consistente do banco (API de backup do SQLite), sem gravar nada no original."""
    src = sqlite3.connect(f'file:{origem}?mode=ro', uri=True, timeout=30)
    dst = sqlite3.connect(destino)
    with dst:
        src.backup(dst)
    src.close(); dst.close()


def dados_empresa(db):
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    r = c.execute("select razao_social, nome, cpf_cnpj, inscricao_estadual, fone, contato from dados_empresa "
                  "where data_hora_deletado is null limit 1").fetchone()
    c.close()
    if not r:
        return {}
    return dict(razao=r[0] or r[1] or '', cnpj=r[2] or '', ie=r[3] or '', fone=r[4] or '', contato=r[5] or '')


def _txt(b):
    return b.decode('utf-8') if isinstance(b, bytes) else (b or '')


def _descompactar(blob):
    """O PDV+ guarda o XML de compra como entrada ZIP sem diretorio central: le o cabecalho local e infla."""
    nl, el = struct.unpack('<HH', blob[26:30])
    return zlib.decompressobj(-15).decompress(blob[30 + nl + el:]).decode('utf-8')


def indexar_originais(pasta):
    """Mapeia chave de acesso -> arquivo nfeProc numa pasta de XMLs originais (busca em subpastas)."""
    idx = {}
    if not pasta or not os.path.isdir(pasta):
        return idx
    for raiz, _, nomes in os.walk(pasta):
        for n in nomes:
            if not n.lower().endswith('.xml'):
                continue
            p = os.path.join(raiz, n)
            cab = _cabeca(p, 4096)
            if 'nfeProc' not in cab:
                continue
            m = re.search(r'\d{44}', n) or re.search(r'Id="NFe(\d{44})"', cab)
            if m:
                idx.setdefault(m.group(m.lastindex or 0), p)
    return idx


def _cabeca(p, n=300):
    try:
        with open(p, 'rb') as f:
            return f.read(n).decode('utf-8', 'ignore')
    except OSError:
        return ''


def extrair_xmls(db, periodo, pasta, pasta_originais=None):
    """Grava em pasta/saidas e pasta/entradas os XMLs do periodo (com 1 dia de folga em cada ponta)."""
    ano, mes = map(int, periodo.split('-'))
    ini = (date(ano, mes, 1) - timedelta(days=1)).isoformat()
    fim = (date(ano, mes, calendar.monthrange(ano, mes)[1]) + timedelta(days=2)).isoformat()
    for d in ('saidas/autorizadas', 'saidas/canceladas', 'entradas'):
        os.makedirs(os.path.join(pasta, d), exist_ok=True)
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    st = dict(saidas=0, canceladas=0, entradas=0, sem_protocolo=[], nao_lancadas=[], icmsst_corrigidos=0,
              entradas_originais=0, entradas_do_banco=0, lancamento={})
    originais = indexar_originais(pasta_originais)

    for (chave, modelo, num, sit, env, ret, retc, envc) in c.execute(
            "select chave_acesso, modelo, numero, situacao, xml_enviado_autorizacao, xml_retornado_autorizacao, "
            "xml_retornado_cancelamento, xml_enviado_cancelamento from nota_fiscal "
            "where data_hora_deletado is null and is_ambiente_producao = 1 and situacao in (1, 3) "
            "and data_hora_emissao >= ? and data_hora_emissao < ?", (ini, fim)):
        nfe = re.search(r'<NFe[ >].*?</NFe>', _txt(env), re.S)
        prot = re.search(r'<protNFe[ >].*?</protNFe>', _txt(ret), re.S)
        if not (nfe and prot and '<cStat>100</cStat>' in prot.group()):
            st['sem_protocolo'].append(f'{"NFC-e" if modelo == "65" else "NF-e"} {num}')
            continue
        sub = 'canceladas' if sit == 3 else 'autorizadas'
        with open(os.path.join(pasta, 'saidas', sub, f'{chave}-nfe.xml'), 'w', encoding='utf-8') as f:
            f.write(f'<?xml version="1.0" encoding="UTF-8"?><nfeProc xmlns="{NS}" versao="4.00">'
                    f'{nfe.group()}{prot.group()}</nfeProc>')
        st['saidas'] += 1
        if sit == 3:
            ev = re.search(r'<evento[ >].*?</evento>', _txt(envc), re.S)
            rev = re.search(r'<retEvento[ >].*?</retEvento>', _txt(retc), re.S)
            if ev and rev:
                with open(os.path.join(pasta, 'saidas', 'canceladas', f'{chave}-can.xml'), 'w', encoding='utf-8') as f:
                    f.write(f'<?xml version="1.0" encoding="UTF-8"?><procEventoNFe xmlns="{NS}" versao="1.00">'
                            f'{ev.group()}{rev.group()}</procEventoNFe>')
            st['canceladas'] += 1

    lancadas = {}
    for idc, dh in c.execute("select id_nota_fiscal_compra, min(data_hora) from entrada where data_hora_deletado is null "
                             "and id_nota_fiscal_compra is not null group by 1"):
        lancadas[idc] = dh
    for (idc, chave, blob, forn, num, emis) in c.execute(
            "select id_nota_fiscal_compra, chave_acesso, xml_compactado, nome_fornecedor, numero, data_hora_emissao "
            "from nota_fiscal_compra where data_hora_deletado is null and xml_compactado is not null "
            "and data_hora_emissao >= ? and data_hora_emissao < ?", (ini, fim)):
        if idc not in lancadas:
            if (emis or '')[:7] == periodo:
                st['nao_lancadas'].append(f'NF-e {num} - {forn}')
            continue
        st['lancamento'][chave] = lancadas[idc]
        destino = os.path.join(pasta, 'entradas', f'{chave}-nfe.xml')
        if chave in originais:
            shutil.copyfile(originais[chave], destino)
            st['entradas_originais'] += 1
        else:
            xml = _descompactar(blob)
            # O PDV+ grava o grupo ICMSST sem a tag CST; no XML original do fornecedor ela e 60.
            xml, n = re.subn(r'(<ICMSST><orig>\d</orig>)(?!<CST>)', r'\1<CST>60</CST>', xml)
            st['icmsst_corrigidos'] += n
            with open(destino, 'w', encoding='utf-8') as f:
                f.write(xml)
            st['entradas_do_banco'] += 1
        st['entradas'] += 1
    c.close()
    return st


def conferencia_banco(db, periodo):
    """Totais calculados direto das tabelas do PDV+, para comparar com o arquivo gerado."""
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    q = lambda s: c.execute(s, (periodo,)).fetchone()
    nfce = q("select count(*), coalesce(sum(valor_total),0) from nota_fiscal where data_hora_deletado is null "
             "and is_ambiente_producao=1 and modelo='65' and situacao=1 and substr(data_hora_emissao,1,7)=?")
    nfe = q("select count(*), coalesce(sum(valor_total),0) from nota_fiscal where data_hora_deletado is null "
            "and is_ambiente_producao=1 and modelo='55' and situacao=1 and substr(data_hora_emissao,1,7)=?")
    ent = q("select count(*), coalesce(sum(n.valor_total),0) from nota_fiscal_compra n where n.data_hora_deletado is null "
            "and n.id_nota_fiscal_compra in (select id_nota_fiscal_compra from entrada where data_hora_deletado is null) "
            "and substr(n.data_hora_emissao,1,7)=?")
    canc = q("select count(*), 0 from nota_fiscal where data_hora_deletado is null and is_ambiente_producao=1 "
             "and situacao=3 and substr(data_hora_emissao,1,7)=?")
    lista_ent = c.execute(
        "select n.numero, n.nome_fornecedor, substr(n.data_hora_emissao,1,10), n.valor_total from nota_fiscal_compra n "
        "where n.data_hora_deletado is null and n.id_nota_fiscal_compra in "
        "(select id_nota_fiscal_compra from entrada where data_hora_deletado is null) "
        "and substr(n.data_hora_emissao,1,7)=? order by n.data_hora_emissao", (periodo,)).fetchall()
    lista_sai = c.execute(
        "select modelo, numero, substr(data_hora_emissao,1,10), valor_total, situacao from nota_fiscal "
        "where data_hora_deletado is null and is_ambiente_producao=1 and situacao in (1,3) "
        "and (modelo='55' or situacao=3) and substr(data_hora_emissao,1,7)=? order by data_hora_emissao", (periodo,)).fetchall()
    por_dia = c.execute(
        "select substr(data_hora_emissao,1,10), count(*), sum(valor_total) from nota_fiscal where data_hora_deletado is null "
        "and is_ambiente_producao=1 and modelo='65' and situacao=1 and substr(data_hora_emissao,1,7)=? group by 1 order by 1",
        (periodo,)).fetchall()
    c.close()
    return dict(nfce=nfce, nfe=nfe, entradas=ent, canceladas=canc,
                lista_entradas=lista_ent, lista_saidas=lista_sai, nfce_por_dia=por_dia)


def _ler_saida(texto):
    r = dict(arquivo=None, documentos={}, valores={}, avisos=[], erros=[], info=[], fora_periodo=0)
    for linha in texto.splitlines():
        if linha.startswith('Arquivo: '):
            r['arquivo'] = linha[9:].split('  (')[0].strip()
        elif linha.startswith('Documentos: '):
            r['documentos'] = eval(linha[12:], {})  # dict impresso pelo gerador
        elif linha.startswith('Valores (autorizados): '):
            r['valores'] = eval(linha[23:], {})
        elif linha.startswith('AVISO: '):
            if 'fora do periodo' in linha:
                r['fora_periodo'] += 1
            else:
                r['avisos'].append(linha[7:])
        elif linha.startswith('ERRO: '):
            r['erros'].append(linha[6:])
        elif linha.startswith('INFO: '):
            r['info'].append(linha[6:])
    return r


def mes_do_xml(caminho):
    m = re.search(r'<dhEmi>(\d{4}-\d{2})', _cabeca(caminho, 6000))
    return m.group(1) if m else None


def _zipar(itens, destino):
    """itens: lista de (caminho_no_disco, nome_no_zip)."""
    with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED) as z:
        for p, nome in itens:
            z.write(p, nome)
    return destino


def montar_zips(xmldir, periodo, cnpj, pasta):
    """Zips com os XMLs do mes (pela data de emissao): entradas e saidas (autorizadas/canceladas)."""
    ent, sai = [], []
    pe = os.path.join(xmldir, 'entradas')
    for n in sorted(os.listdir(pe)):
        p = os.path.join(pe, n)
        if mes_do_xml(p) == periodo:
            ent.append((p, n))
    for sub, rot in (('autorizadas', 'Autorizadas'), ('canceladas', 'Canceladas')):
        ps = os.path.join(xmldir, 'saidas', sub)
        for n in sorted(os.listdir(ps)):
            if not n.endswith('-nfe.xml'):
                continue
            p = os.path.join(ps, n)
            if mes_do_xml(p) != periodo:
                continue
            sai.append((p, f'{rot}/{n}'))
            ev = p.replace('-nfe.xml', '-can.xml')
            if os.path.isfile(ev):
                sai.append((ev, f'{rot}/{os.path.basename(ev)}'))
    ze = _zipar(ent, os.path.join(pasta, f'XML-ENTRADAS-{cnpj}-{periodo}.zip')) if ent else None
    zs = _zipar(sai, os.path.join(pasta, f'XML-SAIDAS-{cnpj}-{periodo}.zip')) if sai else None
    return ze, zs, len(ent), sum(1 for _, n in sai if n.endswith('-nfe.xml'))


def gerar(banco, periodo, telefone, pasta_saida, contato=None, finalidade='1', pasta_originais=None,
          empresa=None, pacote=True):
    """Fluxo completo. Gera em pasta_saida: SINTEGRA .TXT, conferencia .txt e (pacote=True) relatorio Excel
    e zips de XML de entrada e saida. Devolve dict com o resultado."""
    import relatorio_excel
    os.makedirs(pasta_saida, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='aliber_sintegra_')
    try:
        copia = os.path.join(tmp, 'pdv.db')
        copiar_banco(banco, copia)
        empresa = empresa or dados_empresa(copia)
        xmldir = os.path.join(tmp, 'xml')
        st = extrair_xmls(copia, periodo, xmldir, pasta_originais)
        a = argparse.Namespace(
            entradas=os.path.join(xmldir, 'entradas'), saidas=os.path.join(xmldir, 'saidas'),
            periodo=periodo, db=copia, cnpj=None, ie=None, razao=None, uf=None, municipio=None, logradouro=None,
            numero=None, complemento=None, bairro=None, cep=None, contato=contato or None, telefone=telefone,
            fax=None, convenio='3', natureza='3', finalidade=finalidade, data_entrada='emissao', cfop_json=None,
            saida_dir=pasta_saida)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            codigo = gerar_sintegra.gerar(a)
        saida = buf.getvalue()
        r = _ler_saida(saida)
        r.update(codigo=codigo, extracao=st, conferencia=conferencia_banco(copia, periodo), saida_bruta=saida,
                 periodo=periodo, empresa=empresa, arquivos={})
        if r['arquivo']:
            r['arquivo'] = os.path.abspath(r['arquivo'])
            r['arquivos']['sintegra'] = r['arquivo']
        cnpj = re.sub(r'\D', '', empresa.get('cnpj', ''))
        rel = montar_relatorio(r, empresa, periodo)
        r['arquivos']['conferencia'] = os.path.join(pasta_saida, f'CONFERENCIA-{cnpj}-{periodo}.txt')
        with open(r['arquivos']['conferencia'], 'w', encoding='utf-8-sig', newline='') as f:
            f.write(rel)
        if pacote and r['arquivo']:
            ze, zs, ne, ns = montar_zips(xmldir, periodo, cnpj, pasta_saida)
            r['arquivos'].update(xml_entradas=ze, xml_saidas=zs)
            r['xml_qtd'] = dict(entradas=ne, saidas=ns)
            r['arquivos']['excel'] = relatorio_excel.gerar_excel(
                xmldir, periodo, st['lancamento'], empresa,
                os.path.join(pasta_saida, f'RELATORIO-{cnpj}-{periodo}.xlsx'))
        return r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def problemas_bloqueantes(r):
    """Motivos para NAO enviar automaticamente a contabilidade."""
    p = []
    if not r.get('arquivo'):
        p.append('o arquivo SINTEGRA nao foi gerado')
    if r.get('erros'):
        p.append(f'{len(r["erros"])} erro(s) na geracao do SINTEGRA')
    if not r.get('conferencia_ok'):
        p.append('a conferencia com o banco do PDV+ encontrou divergencia')
    return p


def montar_relatorio(r, empresa, periodo):
    """Texto do relatorio de conferencia salvo ao lado do .TXT."""
    br = lambda v: f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    cf, docs, vals = r['conferencia'], r['documentos'], r['valores']
    L = [f'ALIBER SINTEGRA - RELATORIO DE CONFERENCIA',
         f'Empresa: {empresa.get("razao", "")}  CNPJ: {empresa.get("cnpj", "")}',
         f'Periodo: {periodo[5:]}/{periodo[:4]}', f'Arquivo: {r.get("arquivo") or "(nao gerado)"}', '',
         'CONFERENCIA  (banco do PDV+  x  arquivo SINTEGRA)']

    def linha(nome, qb, vb, qa, va):
        ok = 'OK' if qb == qa and abs(vb - va) < 0.01 else 'DIVERGENTE'
        L.append(f'  {nome:<22} banco: {qb:>4} / R$ {br(vb):>12}   arquivo: {qa:>4} / R$ {br(va):>12}   {ok}')
        return ok == 'OK'

    tudo_ok = all([
        linha('NFC-e autorizadas', cf['nfce'][0], cf['nfce'][1], docs.get('NFC-e autorizada', 0), vals.get('NFC-e', 0)),
        linha('NF-e de saida', cf['nfe'][0], cf['nfe'][1], docs.get('NF-e saida', 0), vals.get('NF-e saida', 0)),
        linha('NF-e de entrada', cf['entradas'][0], cf['entradas'][1], docs.get('NF-e entrada', 0), vals.get('NF-e entrada', 0)),
    ])
    canc_arq = docs.get('NFC-e cancelada', 0) + docs.get('NF-e cancelada', 0)
    L.append(f'  {"Canceladas":<22} banco: {cf["canceladas"][0]:>4}{"":19}arquivo: {canc_arq:>4}'
             f'{"":19}{"OK" if cf["canceladas"][0] == canc_arq else "DIVERGENTE"}')
    tudo_ok = tudo_ok and cf['canceladas'][0] == canc_arq
    r['conferencia_ok'] = tudo_ok
    L += ['', 'NF-e DE ENTRADA (lancadas no PDV+)']
    for n, forn, d, v in cf['lista_entradas']:
        L.append(f'  {d[8:10]}/{d[5:7]}  NF {n:<10} R$ {br(v):>12}  {forn}')
    L += ['', 'NF-e DE SAIDA E DOCUMENTOS CANCELADOS']
    for mod, n, d, v, s in cf['lista_saidas']:
        L.append(f'  {d[8:10]}/{d[5:7]}  {"NFC-e" if mod == "65" else "NF-e "} {n:<8} R$ {br(v):>12}  '
                 f'{"CANCELADA" if s == 3 else "autorizada"}')
    L += ['', 'NFC-e AUTORIZADAS POR DIA']
    for d, q, v in cf['nfce_por_dia']:
        L.append(f'  {d[8:10]}/{d[5:7]}  {q:>4} cupons   R$ {br(v):>12}')
    L += ['', 'AVISOS'] + ([f'  - {x}' for x in avisos_usuario(r)] or ['  (nenhum)'])
    if r['erros']:
        L += ['', 'ERROS (o arquivo NAO deve ser enviado)'] + [f'  - {x}' for x in r['erros']]
    return '\r\n'.join(L) + '\r\n'


def avisos_usuario(r):
    av = list(r['avisos'])
    st = r['extracao']
    for x in st['nao_lancadas']:
        av.append(f'{x}: nota de compra do mes ainda NAO lancada no PDV+ (ficou fora do arquivo).')
    for x in st['sem_protocolo']:
        av.append(f'{x}: sem protocolo de autorizacao no PDV+ (contingencia/pendente?); ficou fora do arquivo.')
    return av

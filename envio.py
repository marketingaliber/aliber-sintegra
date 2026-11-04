"""Envio do pacote do SINTEGRA por e-mail (Gmail) e protecao da senha de app."""
import base64, os, re, smtplib, socket, ssl, sys
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

SMTP_HOST, SMTP_PORTA = 'smtp.gmail.com', 465
LIMITE_EMAIL = 18 * 1024 * 1024  # anexos por e-mail (o Gmail aceita 25 MB ja codificado)


# ---------------- senha protegida ----------------
if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    def _dpapi(dados, proteger):
        buf = ctypes.create_string_buffer(dados, len(dados))
        entrada = _BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        saida = _BLOB()
        fn = ctypes.windll.crypt32.CryptProtectData if proteger else ctypes.windll.crypt32.CryptUnprotectData
        if not fn(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(saida.pbData, saida.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(saida.pbData)


def proteger(senha):
    if not senha:
        return ''
    if sys.platform == 'win32':
        return 'dpapi:' + base64.b64encode(_dpapi(senha.encode('utf-8'), True)).decode()
    return 'b64:' + base64.b64encode(senha.encode('utf-8')).decode()


def revelar(guardada):
    if not guardada:
        return ''
    tipo, _, valor = guardada.partition(':')
    if tipo == 'dpapi':
        return _dpapi(base64.b64decode(valor), False).decode('utf-8')
    if tipo == 'b64':
        return base64.b64decode(valor).decode('utf-8')
    return guardada


# ---------------- e-mails ----------------
def lista_emails(texto):
    return [e for e in re.split(r'[;,\s]+', texto or '') if e]


def email_valido(e):
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', e or ''))


class ErroEnvio(Exception):
    pass


def _conectar(usuario, senha):
    try:
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORTA, context=ssl.create_default_context(), timeout=60)
        s.login(usuario, senha.replace(' ', ''))
        return s
    except smtplib.SMTPAuthenticationError:
        raise ErroEnvio('O Gmail recusou o login. Confira o e-mail do cliente e a senha de app '
                        '(é a senha de 16 letras criada em "Senhas de app", não a senha normal do Gmail).')
    except (socket.gaierror, socket.timeout, ConnectionError, OSError) as e:
        raise ErroEnvio(f'Sem conexão com o Gmail (internet desligada ou bloqueada). Detalhe: {e}')


def _mensagem(remetente, nome, para, cc, assunto, texto, html, anexos):
    m = EmailMessage()
    m['From'] = formataddr((nome, remetente))
    m['To'] = ', '.join(para)
    if cc:
        m['Cc'] = ', '.join(cc)
    m['Subject'] = assunto
    m['Message-ID'] = make_msgid(domain='aliber-sintegra.local')
    m.set_content(texto)
    if html:
        m.add_alternative(html, subtype='html')
    for caminho in anexos:
        with open(caminho, 'rb') as f:
            dados = f.read()
        nome_arq = os.path.basename(caminho)
        ext = nome_arq.rsplit('.', 1)[-1].lower()
        tipos = {'zip': ('application', 'zip'), 'xlsx': ('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                 'txt': ('text', 'plain')}
        mt, st = tipos.get(ext, ('application', 'octet-stream'))
        m.add_attachment(dados, maintype=mt, subtype=st, filename=nome_arq)
    return m


def _lotes(anexos):
    """Divide os anexos em lotes que caibam no limite do Gmail."""
    lotes, atual, tam = [], [], 0
    for a in anexos:
        t = os.path.getsize(a)
        if t > LIMITE_EMAIL:
            raise ErroEnvio(f'O arquivo {os.path.basename(a)} tem {t / 1048576:.1f} MB e passa do limite do Gmail. '
                            'Envie esse arquivo manualmente (ex.: Google Drive).')
        if atual and tam + t > LIMITE_EMAIL:
            lotes.append(atual); atual, tam = [], 0
        atual.append(a); tam += t
    if atual:
        lotes.append(atual)
    return lotes


def enviar(usuario, senha, para, cc, assunto, texto, html, anexos, nome='Aliber SINTEGRA'):
    """Envia (em 1 ou mais e-mails, conforme o tamanho). Devolve a quantidade de e-mails enviados."""
    if not usuario or not senha:
        raise ErroEnvio('E-mail do cliente (Gmail) e senha de app não configurados.')
    para = [e for e in para if e]
    if not para:
        raise ErroEnvio('E-mail da contabilidade não configurado.')
    lotes = _lotes(anexos) if anexos else [[]]
    s = _conectar(usuario, senha)
    try:
        for i, lote in enumerate(lotes, start=1):
            sufixo = f' (parte {i} de {len(lotes)})' if len(lotes) > 1 else ''
            m = _mensagem(usuario, nome, para, cc, assunto + sufixo, texto, html, lote)
            s.send_message(m)
    except smtplib.SMTPException as e:
        raise ErroEnvio(f'O Gmail recusou o envio: {e}')
    finally:
        try:
            s.quit()
        except Exception:
            pass
    return len(lotes)


# ---------------- conteudo do e-mail da contabilidade ----------------
def _br(v):
    return f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def montar_email_contabilidade(r, empresa, automatico):
    p = r['periodo']
    mm, aaaa = p[5:], p[:4]
    d, v = r['documentos'], r['valores']
    razao = empresa.get('razao', '')
    cnpj = re.sub(r'\D', '', empresa.get('cnpj', ''))
    cnpj_f = f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}' if len(cnpj) == 14 else cnpj
    assunto = f'SINTEGRA {mm}/{aaaa} - {razao} - CNPJ {cnpj_f}'
    canc = d.get('NFC-e cancelada', 0) + d.get('NF-e cancelada', 0)
    st = r['extracao']
    linhas = [
        ('NF-e de entrada', d.get('NF-e entrada', 0), v.get('NF-e entrada', 0)),
        ('NFC-e autorizadas', d.get('NFC-e autorizada', 0), v.get('NFC-e', 0)),
        ('NF-e de saída autorizadas', d.get('NF-e saida', 0), v.get('NF-e saida', 0)),
    ]
    notas = []
    if st.get('entradas_do_banco'):
        notas.append('Os XMLs de entrada foram extraídos do sistema PDV+, que regrava o arquivo do fornecedor ao '
                     'importar a nota. O conteúdo fiscal confere, mas a assinatura digital desses XMLs pode não ser '
                     'aceita por sistemas que a validem. Se precisar dos originais, nos avise.')
    ipi = [a.split(':')[0] for a in r.get('avisos', []) if 'registro 51 (IPI)' in a]
    if ipi:
        notas.append(f'{len(ipi)} NF-e de entrada têm IPI destacado pelo fornecedor; o registro 51 (IPI) não foi gerado.')
    for x in st.get('nao_lancadas', []):
        notas.append(f'{x}: nota de compra do mês ainda não lançada no PDV+ e por isso fora do arquivo.')
    origem = 'gerado e enviado automaticamente' if automatico else 'gerado e enviado'
    q = r.get('xml_qtd', {})
    anexos_txt = ['SINTEGRA (.TXT)', 'Relatório de entradas e saídas (Excel)']
    anexos_txt.append(f'XMLs de entrada ({q["entradas"]} notas, .zip)' if q.get('entradas')
                      else 'XMLs de entrada: nenhuma NF-e de entrada lançada no mês')
    anexos_txt.append(f'XMLs de saída - NFC-e e NF-e, autorizadas e canceladas ({q["saidas"]} documentos, .zip)'
                      if q.get('saidas') else 'XMLs de saída: nenhum documento de saída no mês')
    texto = [f'Prezados,', '', f'Segue o fechamento fiscal de {mm}/{aaaa} da empresa {razao} (CNPJ {cnpj_f}).', '',
             'Resumo:']
    texto += [f'  - {n}: {q} - R$ {_br(val)}' for n, q, val in linhas]
    texto += [f'  - Documentos cancelados: {canc}', '', 'Anexos:'] + [f'  - {a}' for a in anexos_txt]
    if notas:
        texto += ['', 'Observações:'] + [f'  - {n}' for n in notas]
    texto += ['', f'Arquivo {origem} pelo Aliber SINTEGRA (Aliber Informática).']
    tr = ''.join(f'<tr><td style="padding:4px 12px 4px 0">{n}</td><td style="padding:4px 12px;text-align:right">{q}</td>'
                 f'<td style="padding:4px 0 4px 12px;text-align:right">R$ {_br(val)}</td></tr>' for n, q, val in linhas)
    html = (f'<div style="font-family:Arial,sans-serif;font-size:14px;color:#222">'
            f'<p>Prezados,</p><p>Segue o fechamento fiscal de <b>{mm}/{aaaa}</b> da empresa <b>{razao}</b> '
            f'(CNPJ {cnpj_f}).</p>'
            f'<table style="border-collapse:collapse;font-size:14px">{tr}'
            f'<tr><td style="padding:4px 12px 4px 0">Documentos cancelados</td>'
            f'<td style="padding:4px 12px;text-align:right">{canc}</td><td></td></tr></table>'
            f'<p><b>Anexos</b></p><ul>' + ''.join(f'<li>{a}</li>' for a in anexos_txt) + '</ul>'
            + (('<p><b>Observações</b></p><ul>' + ''.join(f'<li>{n}</li>' for n in notas) + '</ul>') if notas else '')
            + f'<p style="color:#777;font-size:12px">Arquivo {origem} pelo '
              f'<span style="color:#E1251B;font-weight:bold">Aliber</span> '
              f'<span style="color:#1E5FD0;font-weight:bold">SINTEGRA</span> · Aliber Informática</p></div>')
    anexos = [r['arquivos'][k] for k in ('sintegra', 'excel', 'xml_entradas', 'xml_saidas') if r['arquivos'].get(k)]
    return assunto, '\n'.join(texto), html, anexos

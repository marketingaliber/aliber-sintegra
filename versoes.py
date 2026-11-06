"""Troca de versao do Aliber SINTEGRA (area do tecnico).

Mesmo modelo do Aliber Print: sem aviso de versao nova; o tecnico escolhe a versao em
Configuracoes > Escolher versao, protegido pela senha do tecnico (so o hash fica no codigo).
As versoes publicadas ficam na pasta versoes/ do repositorio publico marketingaliber/aliber-sintegra:
  versoes/Instalar-AliberSintegra-X.Y.exe   (instalador)
  versoes/NOTAS-X.Y.md                      (o que mudou, para o tecnico; opcional)
"""
import hashlib, hmac, json, os, re, subprocess, sys, tempfile, time, urllib.request

REPO = 'marketingaliber/aliber-sintegra'
PASTA = 'versoes'
API = f'https://api.github.com/repos/{REPO}/contents/{PASTA}?ref=main'
RE_INSTALADOR = re.compile(r'^Instalar-AliberSintegra-(\d+(?:\.\d+){1,2})\.exe$')
UA = {'User-Agent': 'AliberSintegra', 'Accept': 'application/vnd.github+json'}

# Senha do tecnico (a mesma do Aliber Print). PBKDF2-SHA256; para trocar, gere novo sal/hash.
SENHA = dict(sal='a48a4575c10f36585086cb5f92d09227', iteracoes=120000,
             hash='0f8f8eac67ecb2d3446c067b45e932989d3bdd9c66f03e7d998b603e67c99783')

_erros, _bloqueado_ate = 0, 0.0


class ErroVersao(Exception):
    pass


def conferir_senha(senha):
    """True se a senha do tecnico estiver certa. 5 erros seguidos bloqueiam por 1 minuto."""
    global _erros, _bloqueado_ate
    if time.time() < _bloqueado_ate:
        raise ErroVersao('Muitas tentativas erradas. Aguarde um minuto e tente de novo.')
    calc = hashlib.pbkdf2_hmac('sha256', (senha or '').encode('utf-8'), SENHA['sal'].encode(), SENHA['iteracoes'], 32)
    if hmac.compare_digest(calc.hex(), SENHA['hash']):
        _erros = 0
        return True
    _erros += 1
    if _erros >= 5:
        _bloqueado_ate, _erros = time.time() + 60, 0
    return False


def comparar(a, b):
    pa, pb = [int(x) for x in a.split('.')], [int(x) for x in b.split('.')]
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa)); pb += [0] * (n - len(pb))
    return (pa > pb) - (pa < pb)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise ErroVersao('O GitHub limitou as consultas deste computador por alguns minutos. Tente de novo daqui a pouco.')
        if e.code == 404:
            raise ErroVersao('Nenhuma versão publicada foi encontrada.')
        raise ErroVersao(f'O GitHub respondeu com erro {e.code}.')
    except OSError:
        raise ErroVersao('Sem acesso à internet para buscar as versões. Confira a conexão deste computador.')


def listar(atual):
    """Versoes publicadas, da mais nova para a mais antiga."""
    itens = json.loads(_get(API))
    notas = {}
    for f in itens:
        m = re.match(r'^NOTAS-(\d+(?:\.\d+){1,2})\.md$', f.get('name', ''))
        if m:
            notas[m.group(1)] = f.get('download_url')
    vers = []
    for f in itens:
        m = RE_INSTALADOR.match(f.get('name', ''))
        if not m:
            continue
        v = m.group(1)
        vers.append(dict(versao=v, arquivo=f['name'], url=f['download_url'], tamanho=f.get('size', 0),
                         sha=f.get('sha', ''), url_notas=notas.get(v),
                         instalada=comparar(v, atual) == 0, mais_antiga=comparar(v, atual) < 0,
                         sem_seletor=comparar(v, '2.4') < 0))
    vers.sort(key=lambda x: [int(p) for p in x['versao'].split('.')], reverse=True)
    return vers


def notas(item):
    if not item.get('url_notas'):
        return ''
    try:
        return _get(item['url_notas']).decode('utf-8', 'replace')[:6000]
    except ErroVersao:
        return ''


def baixar(item, progresso=None):
    """Baixa o instalador para a pasta temporaria e confere a integridade (hash do GitHub)."""
    destino = os.path.join(tempfile.gettempdir(), item['arquivo'])
    req = urllib.request.Request(item['url'], headers={'User-Agent': 'AliberSintegra'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(destino + '.parcial', 'wb') as f:
            total, lido = item.get('tamanho') or int(r.headers.get('Content-Length') or 0), 0
            while True:
                bloco = r.read(65536)
                if not bloco:
                    break
                f.write(bloco); lido += len(bloco)
                if progresso and total:
                    progresso(min(100, lido * 100 // total))
    except OSError:
        raise ErroVersao('A conexão caiu durante o download. Tente de novo.')
    with open(destino + '.parcial', 'rb') as f:
        dados = f.read()
    if item.get('sha'):
        # o "sha" da API do GitHub e o SHA-1 de "blob <tamanho>\0<conteudo>"
        sha = hashlib.sha1(b'blob %d\0' % len(dados) + dados).hexdigest()
        if sha != item['sha']:
            os.remove(destino + '.parcial')
            raise ErroVersao('O arquivo baixado veio corrompido. Tente de novo.')
    os.replace(destino + '.parcial', destino)
    return destino


def instalar(caminho):
    """Abre o instalador em modo silencioso. Ele substitui os arquivos e reabre o programa no final."""
    if sys.platform != 'win32':
        raise ErroVersao('A instalação só funciona no Windows.')
    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([caminho, '/S'], creationflags=DETACHED, close_fds=True)

"""Rotina automatica: a partir do dia 1o, ao ligar o computador, gera o SINTEGRA do mes anterior,
copia para a area de trabalho e envia o pacote para a contabilidade."""
import json, os, shutil, socket, sys, threading, time, traceback
from datetime import date, datetime

APP_DIR = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'AliberSintegra')
ESTADO = os.path.join(APP_DIR, 'estado.json')
LOG = os.path.join(APP_DIR, 'automatico.log')
CHAVE_RUN = r'Software\Microsoft\Windows\CurrentVersion\Run'
NOME_RUN = 'AliberSintegra'
ESPERAS_REENVIO = [2, 5, 10, 15, 30, 30, 30]  # minutos entre tentativas de envio (~2 h no total)


# ---------------- utilidades ----------------
def log(msg):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'{datetime.now():%d/%m/%Y %H:%M:%S}  {msg}\n')
    except Exception:
        pass


def mes_anterior(hoje=None):
    hoje = hoje or date.today()
    a, m = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    return f'{a}-{m:02d}'


def mes_atual(hoje=None):
    hoje = hoje or date.today()
    return f'{hoje.year}-{hoje.month:02d}'


def proximo_envio(estado, hoje=None):
    """(data do proximo envio automatico, periodo referente)."""
    hoje = hoje or date.today()
    alvo = mes_anterior(hoje)
    if alvo >= estado.get('inicio_auto', '9999') and alvo not in estado.get('enviados', {}):
        return hoje, alvo
    a, m = (hoje.year, hoje.month + 1) if hoje.month < 12 else (hoje.year + 1, 1)
    return date(a, m, 1), mes_atual(hoje)


def carregar_estado():
    try:
        with open(ESTADO, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_estado(e):
    os.makedirs(APP_DIR, exist_ok=True)
    tmp = ESTADO + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(e, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ESTADO)


def marcar_enviado(periodo, automatico):
    e = carregar_estado()
    e.setdefault('enviados', {})[periodo] = dict(data=f'{datetime.now():%d/%m/%Y %H:%M}',
                                                 modo='automático' if automatico else 'manual')
    salvar_estado(e)


def area_de_trabalho():
    """Pasta da Area de Trabalho do usuario (inclusive quando redirecionada para o OneDrive)."""
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0 and os.path.isdir(buf.value):
                return buf.value
        except Exception:
            pass
    for p in (os.path.join(os.path.expanduser('~'), 'Desktop'),
              os.path.join(os.path.expanduser('~'), 'OneDrive', 'Desktop'),
              os.path.join(os.path.expanduser('~'), 'Área de Trabalho')):
        if os.path.isdir(p):
            return p
    return os.path.expanduser('~')


def comando_inicializacao():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --automatico'
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
    return f'"{pyw if os.path.isfile(pyw) else sys.executable}" "{app}" --automatico'


def configurar_inicializacao(ativar):
    """Liga/desliga a execucao automatica ao entrar no Windows (HKCU\\...\\Run). Devolve True se ok."""
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as k:
            if ativar:
                winreg.SetValueEx(k, NOME_RUN, 0, winreg.REG_SZ, comando_inicializacao())
            else:
                try:
                    winreg.DeleteValue(k, NOME_RUN)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        log('Falha ao configurar inicialização: ' + traceback.format_exc())
        return False


class InstanciaUnica:
    """Impede duas rotinas automaticas ao mesmo tempo."""

    def __init__(self, porta=47913):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.s.bind(('127.0.0.1', porta))
            self.ok = True
        except OSError:
            self.ok = False


# ---------------- rotina ----------------
def precisa_rodar(cfg, estado, hoje=None):  # noqa
    if not cfg.get('auto'):
        return None
    alvo = mes_anterior(hoje)
    if alvo < estado.get('inicio_auto', '9999'):
        return None
    if alvo in estado.get('enviados', {}):
        return None
    return alvo


def inicializacao_registrada():
    """True/False se o programa esta registrado para iniciar com o Windows (None fora do Windows)."""
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as k:
            valor, _ = winreg.QueryValueEx(k, NOME_RUN)
        return '--automatico' in valor
    except OSError:
        return False


def executar(cfg, avisar, espera_inicial=45, dormir=time.sleep, hoje=None, teste=False):
    """Executa a rotina. `avisar(tipo, titulo, texto)` mostra notificacoes (tipo: ok, alerta, erro).
    teste=True (modo simulacao): ignora o registro de envios, nao grava nada nele, salva em pasta TESTE,
    copia o .TXT para a Area de Trabalho com prefixo TESTE- e envia SO para o e-mail do cliente."""
    import motor_pdv, envio
    estado = carregar_estado()
    T = 'TESTE · ' if teste else ''
    pre = '[TESTE] ' if teste else ''
    if teste:
        alvo = mes_anterior(hoje)
    else:
        alvo = precisa_rodar(cfg, estado, hoje)
        if not alvo:
            return 'nada'
    mm, aaaa = alvo[5:], alvo[:4]
    log(f'{pre}Rotina automática para {alvo} (data {"simulada" if teste else "do sistema"}: '
        f'{(hoje or date.today()):%d/%m/%Y}): aguardando {espera_inicial}s')
    dormir(espera_inicial)

    if not cfg.get('telefone'):
        avisar('erro', f'{T}Configuração incompleta', 'Abra o Aliber SINTEGRA e preencha as Configurações.')
        return 'erro'
    banco = motor_pdv.localizar_banco(cfg.get('banco'))
    if not banco:
        log(f'{pre}Banco do PDV+ não encontrado')
        avisar('erro', f'{T}Aliber SINTEGRA', 'Banco do PDV+ não encontrado. '
               'Abra o Aliber SINTEGRA e confira as configurações.')
        return 'erro'
    base = cfg.get('pasta') or os.path.join(os.path.expanduser('~'), 'Documents', 'SINTEGRA')
    pasta = os.path.join(base, 'TESTE', alvo) if teste else os.path.join(base, alvo)
    try:
        r = motor_pdv.gerar(banco, alvo, cfg['telefone'], pasta, cfg.get('contato') or None, '1',
                            cfg.get('pasta_xml_originais') or None)
    except Exception:
        log(f'{pre}Erro ao gerar: ' + traceback.format_exc())
        avisar('erro', f'{T}SINTEGRA {mm}/{aaaa} não foi gerado', 'Ocorreu um erro. Fale com a Aliber Informática.')
        return 'erro'

    desk = None
    if r.get('arquivo'):
        try:
            desk = os.path.join(area_de_trabalho(), ('TESTE-' if teste else '') + os.path.basename(r['arquivo']))
            shutil.copyfile(r['arquivo'], desk)
        except Exception:
            log(f'{pre}Falha ao copiar para a área de trabalho: ' + traceback.format_exc())
    if not teste:
        estado = carregar_estado()
        estado.setdefault('gerados', {})[alvo] = f'{datetime.now():%d/%m/%Y %H:%M}'
        salvar_estado(estado)
    log(f'{pre}Gerado {r.get("arquivo")} | área de trabalho: {desk}')

    bloqueios = motor_pdv.problemas_bloqueantes(r)
    if bloqueios:
        log(f'{pre}Envio bloqueado: ' + '; '.join(bloqueios))
        avisar('erro', f'{T}SINTEGRA {mm}/{aaaa} NÃO foi enviado',
               'O arquivo precisa ser conferido antes de ir para a contabilidade (' + '; '.join(bloqueios) +
               '). Fale com a Aliber Informática.')
        return 'bloqueado'

    assunto, texto, html, anexos = envio.montar_email_contabilidade(r, r['empresa'], automatico=True)
    para_real = envio.lista_emails(cfg.get('email_contabilidade'))
    if teste:
        para, cc = envio.lista_emails(cfg.get('email_cliente')), []
        reg = inicializacao_registrada()
        reg_txt = {True: 'SIM', False: 'NÃO (abra Configurações e clique em Salvar)', None: 'não verificado'}[reg]
        aviso = (f'ESTE É UM TESTE DO ENVIO AUTOMÁTICO (data simulada: {hoje:%d/%m/%Y}).\n'
                 f'No envio real, este e-mail iria para: {", ".join(para_real) or "(contabilidade não configurada)"}, '
                 f'com cópia para {cfg.get("email_cliente")}.\n'
                 f'Programa registrado para iniciar com o Windows: {reg_txt}.\n' + '-' * 60 + '\n\n')
        texto = aviso + texto
        html = ('<div style="font-family:Arial,sans-serif;background:#FFF4D6;border:1px solid #F2B33D;padding:10px 14px;'
                'margin-bottom:14px;font-size:13px">' + aviso.replace('-' * 60, '').strip().replace('\n', '<br>')
                + '</div>' + html)
        assunto = '[TESTE] ' + assunto
        esperas = [0]
    else:
        para, cc = para_real, envio.lista_emails(cfg.get('email_cliente'))
        esperas = [0] + ESPERAS_REENVIO
    try:
        senha = envio.revelar(cfg.get('senha_app'))
    except Exception:
        log(f'{pre}Não foi possível ler a senha de app: ' + traceback.format_exc()); senha = ''
    ultima = None
    for tentativa, espera in enumerate(esperas, start=1):
        if espera:
            dormir(espera * 60)
        try:
            n = envio.enviar(cfg.get('email_cliente'), senha, para, cc, assunto, texto, html, anexos)
            if not teste:
                marcar_enviado(alvo, automatico=True)
            log(f'{pre}Enviado para {para} em {n} e-mail(s) (tentativa {tentativa})')
            pend = r['extracao'].get('nao_lancadas', [])
            extra = (f' ATENÇÃO: {len(pend)} nota(s) de compra de {mm}/{aaaa} ainda não lançada(s) no PDV+ '
                     f'ficaram fora do arquivo ({"; ".join(pend[:3])}).') if pend else ''
            if teste:
                avisar('alerta' if pend else 'ok', f'{T}SINTEGRA {mm}/{aaaa} gerado e enviado',
                       f'Teste concluído: arquivo na Área de Trabalho (TESTE-...TXT) e e-mail enviado para '
                       f'{", ".join(para)}. No envio real iria para {", ".join(para_real) or "(não configurado)"}. '
                       'Nada foi marcado como enviado.' + extra)
            else:
                avisar('alerta' if pend else 'ok', f'SINTEGRA {mm}/{aaaa} enviado',
                       f'O arquivo foi salvo na Área de Trabalho e enviado para a contabilidade '
                       f'({", ".join(para)}) com os XMLs e o relatório em Excel.' + extra)
            return 'enviado'
        except envio.ErroEnvio as e:
            ultima = str(e)
            log(f'{pre}Tentativa {tentativa} falhou: {e}')
            if 'recusou o login' in ultima or 'não configurado' in ultima or 'limite do Gmail' in ultima:
                break  # nao adianta repetir
    if teste:
        avisar('erro', f'{T}SINTEGRA {mm}/{aaaa} gerado, mas o e-mail falhou',
               f'O arquivo está na Área de Trabalho (TESTE-...TXT). O envio falhou: {ultima}')
    else:
        avisar('alerta', f'SINTEGRA {mm}/{aaaa} gerado, mas NÃO enviado',
               f'O arquivo está na Área de Trabalho. O envio para a contabilidade falhou: {ultima} '
               'Uma nova tentativa será feita na próxima vez que o computador for ligado.')
    return 'falhou_envio'


# ---------------- notificacao (janela no canto da tela) ----------------
def rodar_em_segundo_plano(cfg, hoje=None):
    """hoje=None: modo normal (data do Windows). hoje=date(...): modo simulacao (teste)."""
    import tkinter as tk
    teste = hoje is not None
    trava = InstanciaUnica()
    if not trava.ok:
        return
    estado = carregar_estado()
    if not teste and not precisa_rodar(cfg, estado):
        if cfg.get('auto'):
            d, ref = proximo_envio(estado)
            log(f'Verificado na inicialização: nada pendente. Próximo envio: {d:%d/%m/%Y} (ref. {ref[5:]}/{ref[:4]})')
        return
    from app import BG, CARD, TXT, SUAVE, VERDE, AMARELO, VERMELHO, FONTE, recurso
    root = tk.Tk()
    root.withdraw()
    fila, fim = [], {'ok': False}
    cores = {'ok': VERDE, 'alerta': AMARELO, 'erro': VERMELHO}

    def avisar(tipo, titulo, texto):
        fila.append((tipo, titulo, texto))

    def trabalho():
        try:
            if teste:
                executar(cfg, avisar, espera_inicial=3, hoje=hoje, teste=True)
            else:
                executar(cfg, avisar)
        except Exception:
            log('Falha inesperada: ' + traceback.format_exc())
        finally:
            fim['ok'] = True

    def mostrar(tipo, titulo, texto):
        j = tk.Toplevel(root)
        j.overrideredirect(True)
        j.attributes('-topmost', True)
        j.configure(bg=cores[tipo])
        corpo = tk.Frame(j, bg=CARD)
        corpo.pack(fill='both', expand=True, padx=(5, 0))
        topo = tk.Frame(corpo, bg=CARD); topo.pack(fill='x', padx=16, pady=(12, 0))
        tk.Label(topo, text='Aliber', bg=CARD, fg=VERMELHO, font=(FONTE, 10, 'bold')).pack(side='left')
        tk.Label(topo, text=' SINTEGRA', bg=CARD, fg='#3D8BFF', font=(FONTE, 10, 'bold')).pack(side='left')
        x = tk.Label(topo, text='✕', bg=CARD, fg=SUAVE, cursor='hand2', font=(FONTE, 11))
        x.pack(side='right'); x.bind('<Button-1>', lambda e: j.destroy())
        tk.Label(corpo, text=titulo, bg=CARD, fg=cores[tipo], font=(FONTE, 12, 'bold'), anchor='w',
                 wraplength=380, justify='left').pack(fill='x', padx=16, pady=(6, 2))
        tk.Label(corpo, text=texto, bg=CARD, fg=TXT, font=(FONTE, 9), anchor='w', wraplength=380,
                 justify='left').pack(fill='x', padx=16, pady=(0, 14))
        j.update_idletasks()
        w, h = 420, j.winfo_reqheight()
        j.geometry(f'{w}x{h}+{j.winfo_screenwidth() - w - 16}+{j.winfo_screenheight() - h - 60}')
        j.after(60000 if tipo != 'ok' else 30000, lambda: j.winfo_exists() and j.destroy())

    def ciclo():
        while fila:
            mostrar(*fila.pop(0))
        abertas = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if fim['ok'] and not abertas and not fila:
            root.destroy(); return
        root.after(500, ciclo)

    threading.Thread(target=trabalho, daemon=True).start()
    root.after(500, ciclo)
    root.mainloop()

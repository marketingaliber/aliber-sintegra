"""Aliber SINTEGRA - gera o arquivo SINTEGRA direto do banco do PDV+."""
import json, os, queue, subprocess, sys, threading, traceback, webbrowser
from datetime import date
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import motor_pdv, envio, automatico, versoes

VERSAO = '2.4'
APP_DIR = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'AliberSintegra')
CONFIG = os.path.join(APP_DIR, 'config.json')

# Paleta Aliber (painel escuro, vermelho e azul do logo)
BG, CARD, CARD2, LINHA = '#11151B', '#1A2029', '#222A35', '#2C3542'
TXT, SUAVE = '#E9EDF2', '#8B96A5'
VERMELHO, VERMELHO_HOVER, AZUL = '#E1251B', '#F0453C', '#3D8BFF'
VERDE, AMARELO = '#2FBF71', '#F2B33D'
FONTE = 'Segoe UI' if sys.platform == 'win32' else 'DejaVu Sans'

FINALIDADES = {'Normal': '1', 'Retificação total': '2', 'Retificação aditiva': '5'}


def recurso(nome):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nome)


def carregar_config():
    try:
        with open(CONFIG, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def salvar_config(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def registrar_erro(texto):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(os.path.join(APP_DIR, 'erros.log'), 'a', encoding='utf-8') as f:
            f.write(f'--- {date.today().isoformat()} v{VERSAO}\n{texto}\n')
    except Exception:
        pass


def abrir(caminho):
    if sys.platform == 'win32':
        os.startfile(caminho)
    else:
        subprocess.Popen(['xdg-open', caminho])


def br(v):
    return f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def fmt_cnpj(c):
    c = ''.join(ch for ch in c if ch.isdigit())
    return f'{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}' if len(c) == 14 else c


def meses(n=18):
    hoje = date.today(); a, m = hoje.year, hoje.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            a, m = a - 1, 12
        out.append(f'{m:02d}/{a}')
    return out  # o primeiro e o mes passado


def pasta_documentos():
    return os.path.join(os.path.expanduser('~'), 'Documents', 'SINTEGRA')


def aviso_amigavel(x):
    if 'registro 51 (IPI)' in x:
        return (x.split(':')[0] + ': o fornecedor destacou IPI. O registro 51 (IPI) não é gerado; '
                'normalmente só é exigido de contribuinte do IPI. Confirme com a contabilidade.')
    return x


class Botao(tk.Label):
    """Botao plano com hover (o ttk no Windows nao aceita cor de fundo)."""

    def __init__(self, pai, texto, comando, cor=VERMELHO, hover=VERMELHO_HOVER, fg='white', grande=False, **kw):
        super().__init__(pai, text=texto, bg=cor, fg=fg, cursor='hand2',
                         font=(FONTE, 12 if grande else 10, 'bold' if grande else 'normal'),
                         padx=22 if grande else 14, pady=10 if grande else 6, **kw)
        self.cor, self.hover, self.comando, self.ativo = cor, hover, comando, True
        self.bind('<Enter>', lambda e: self.ativo and self.config(bg=self.hover))
        self.bind('<Leave>', lambda e: self.config(bg=self.cor if self.ativo else LINHA))
        self.bind('<Button-1>', lambda e: self.ativo and self.comando())

    def habilitar(self, sim):
        self.ativo = sim
        self.config(bg=self.cor if sim else LINHA, fg='white' if sim else SUAVE, cursor='hand2' if sim else 'arrow')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f'Aliber SINTEGRA {VERSAO}')
        self.configure(bg=BG)
        self.geometry('780x780'); self.minsize(720, 720)
        try:
            self.iconbitmap(recurso('icone.ico'))
        except Exception:
            pass
        self.cfg = carregar_config()
        self.fila = queue.Queue()
        self.ultimo = None
        self.empresa = {}
        self._estilo()
        self._montar()
        self.after(150, self._iniciar)

    # ---------- layout ----------
    def _estilo(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        s.configure('TCombobox', fieldbackground=CARD2, background=CARD2, foreground=TXT, arrowcolor=TXT,
                    bordercolor=LINHA, lightcolor=CARD2, darkcolor=CARD2, padding=6)
        s.map('TCombobox', fieldbackground=[('readonly', CARD2)], foreground=[('readonly', TXT)],
              selectbackground=[('readonly', CARD2)], selectforeground=[('readonly', TXT)])
        self.option_add('*TCombobox*Listbox.background', CARD2)
        self.option_add('*TCombobox*Listbox.foreground', TXT)
        self.option_add('*TCombobox*Listbox.selectBackground', AZUL)
        self.option_add('*TCombobox*Listbox.font', (FONTE, 10))

    def _lbl(self, pai, texto, tam=10, cor=TXT, peso='normal', **kw):
        return tk.Label(pai, text=texto, bg=pai['bg'], fg=cor, font=(FONTE, tam, peso), **kw)

    def _montar(self):
        # Cabecalho
        topo = tk.Frame(self, bg=BG); topo.pack(fill='x', padx=28, pady=(22, 6))
        marca = tk.Frame(topo, bg=BG); marca.pack(side='left')
        tk.Label(marca, text='Aliber', bg=BG, fg=VERMELHO, font=(FONTE, 24, 'bold')).pack(side='left')
        tk.Label(marca, text=' SINTEGRA', bg=BG, fg=AZUL, font=(FONTE, 24, 'bold')).pack(side='left')
        Botao(topo, '⚙  Configurações', self.abrir_config, cor=CARD2, hover=LINHA).pack(side='right')
        Botao(topo, '▶  Simular envio automático', self.abrir_simulacao, cor=CARD2, hover=LINHA).pack(side='right', padx=8)
        self._lbl(self, 'Arquivo SINTEGRA gerado direto do banco do PDV+  ·  Convênio ICMS 57/95',
                  9, SUAVE).pack(anchor='w', padx=30)
        tk.Frame(self, bg=VERMELHO, height=3).pack(fill='x', padx=30, pady=(12, 16))

        # Empresa
        self.card_emp = tk.Frame(self, bg=CARD); self.card_emp.pack(fill='x', padx=28)
        self.lb_razao = self._lbl(self.card_emp, 'Procurando o banco do PDV+…', 13, TXT, 'bold')
        self.lb_razao.pack(anchor='w', padx=18, pady=(14, 0))
        self.lb_docs = self._lbl(self.card_emp, '', 9, SUAVE)
        self.lb_docs.pack(anchor='w', padx=18, pady=(2, 0))
        self.lb_auto = self._lbl(self.card_emp, '', 9, SUAVE, justify='left', wraplength=680)
        self.lb_auto.pack(anchor='w', padx=18, pady=(6, 14))

        # Controles
        ctl = tk.Frame(self, bg=BG); ctl.pack(fill='x', padx=28, pady=18)
        c1 = tk.Frame(ctl, bg=BG); c1.pack(side='left')
        self._lbl(c1, 'MÊS DE REFERÊNCIA', 8, SUAVE, 'bold').pack(anchor='w')
        self.cb_mes = ttk.Combobox(c1, values=meses(), state='readonly', width=12, font=(FONTE, 11))
        self.cb_mes.current(0); self.cb_mes.pack(anchor='w', pady=(4, 0))
        c2 = tk.Frame(ctl, bg=BG); c2.pack(side='left', padx=18)
        self._lbl(c2, 'FINALIDADE', 8, SUAVE, 'bold').pack(anchor='w')
        self.cb_fin = ttk.Combobox(c2, values=list(FINALIDADES), state='readonly', width=18, font=(FONTE, 11))
        self.cb_fin.current(0); self.cb_fin.pack(anchor='w', pady=(4, 0))
        self.bt_gerar = Botao(ctl, 'Gerar SINTEGRA', self.gerar, grande=True)
        self.bt_gerar.pack(side='right', anchor='s')

        # Resultado
        self.res = tk.Frame(self, bg=CARD); self.res.pack(fill='both', expand=True, padx=28, pady=(0, 10))
        self.lb_status = self._lbl(self.res, 'Escolha o mês e clique em Gerar SINTEGRA.', 12, SUAVE, 'bold')
        self.lb_status.pack(anchor='w', padx=18, pady=(16, 2))
        self.lb_arquivo = self._lbl(self.res, '', 9, SUAVE, wraplength=660, justify='left')
        self.lb_arquivo.pack(anchor='w', padx=18)

        self.tiles = tk.Frame(self.res, bg=CARD); self.tiles.pack(fill='x', padx=12, pady=12)
        self.tile = {}
        for i, (k, t) in enumerate([('ent', 'Entradas (NF-e)'), ('nfce', 'NFC-e'), ('nfe', 'NF-e de saída'),
                                    ('canc', 'Canceladas')]):
            f = tk.Frame(self.tiles, bg=CARD2); f.grid(row=0, column=i, sticky='nsew', padx=6)
            self.tiles.columnconfigure(i, weight=1)
            self._lbl(f, t.upper(), 8, SUAVE, 'bold').pack(anchor='w', padx=12, pady=(10, 0))
            q = self._lbl(f, '—', 20, TXT, 'bold'); q.pack(anchor='w', padx=12)
            v = self._lbl(f, '', 9, SUAVE); v.pack(anchor='w', padx=12, pady=(0, 10))
            self.tile[k] = (q, v)

        self.lb_conf = self._lbl(self.res, '', 10, SUAVE, 'bold')
        self.lb_conf.pack(anchor='w', padx=18)
        self._lbl(self.res, 'AVISOS', 8, SUAVE, 'bold').pack(anchor='w', padx=18, pady=(12, 4))
        caixa = tk.Frame(self.res, bg=CARD2); caixa.pack(fill='both', expand=True, padx=18)
        self.tx_avisos = tk.Text(caixa, bg=CARD2, fg=TXT, relief='flat', wrap='word', height=6,
                                 font=(FONTE, 9), padx=10, pady=8, insertbackground=TXT, highlightthickness=0)
        sb = ttk.Scrollbar(caixa, command=self.tx_avisos.yview)
        self.tx_avisos.configure(yscrollcommand=sb.set, state='disabled')
        sb.pack(side='right', fill='y'); self.tx_avisos.pack(fill='both', expand=True)
        self.tx_avisos.tag_configure('erro', foreground=VERMELHO_HOVER)
        self.tx_avisos.tag_configure('aviso', foreground=AMARELO)

        acoes = tk.Frame(self.res, bg=CARD); acoes.pack(fill='x', padx=18, pady=14)
        self.bt_pasta = Botao(acoes, 'Abrir pasta', self.abrir_pasta, cor=AZUL, hover='#5C9DFF')
        self.bt_pasta.pack(side='left')
        self.bt_rel = Botao(acoes, 'Abrir relatório Excel', self.abrir_relatorio, cor=CARD2, hover=LINHA)
        self.bt_rel.pack(side='left', padx=10)
        self.bt_enviar = Botao(acoes, '✉  Enviar para a contabilidade', self.enviar_contabilidade,
                               cor=VERDE, hover='#45D486')
        self.bt_enviar.pack(side='right')
        self.bt_pasta.habilitar(False); self.bt_rel.habilitar(False); self.bt_enviar.habilitar(False)

        self._lbl(self, f'Aliber Informática  ·  versão {VERSAO}', 8, SUAVE).pack(side='bottom', pady=(0, 10))

    # ---------- dados ----------
    def _iniciar(self):
        banco = motor_pdv.localizar_banco(self.cfg.get('banco'))
        if banco:
            self.cfg['banco'] = banco
            try:
                self.empresa = motor_pdv.dados_empresa(banco)
            except Exception:
                registrar_erro(traceback.format_exc()); self.empresa = {}
        if self.cfg.get('auto'):
            automatico.configurar_inicializacao(True)   # mantém o início com o Windows apontando para esta instalação
        self._mostrar_empresa()
        if not banco or not self.cfg.get('telefone') or 'email_contabilidade' not in self.cfg:
            messagebox.showinfo('Configuração', 'Preencha as configurações: telefone de contato, e-mail da '
                                'contabilidade e e-mail do cliente (Gmail) para o envio automático.', parent=self)
            self.abrir_config()

    def _mostrar_empresa(self):
        e = self.empresa
        if e.get('cnpj'):
            self.lb_razao.config(text=e.get('razao') or 'Empresa sem razão social', fg=TXT)
            self.lb_docs.config(text=f'CNPJ {fmt_cnpj(e["cnpj"])}   ·   IE {e.get("ie", "")}   ·   '
                                     f'Tel. {self.cfg.get("telefone") or "não configurado"}')
        else:
            self.lb_razao.config(text='Banco do PDV+ não encontrado', fg=VERMELHO_HOVER)
            self.lb_docs.config(text='Abra as Configurações e indique onde está o banco (arquivo .db).')
        self._mostrar_auto()

    def _mostrar_auto(self):
        est = automatico.carregar_estado()
        env = est.get('enviados', {})
        ult = ''
        if env:
            p = max(env)
            ult = f'\nÚltimo envio: {p[5:]}/{p[:4]} em {env[p]["data"]} ({env[p]["modo"]})'
        if self.cfg.get('auto'):
            d, ref = automatico.proximo_envio(est)
            quando = 'hoje' if d == date.today() else d.strftime('%d/%m/%Y')
            self.lb_auto.config(text=f'✉  Envio automático ATIVO  ·  próximo: {quando} (ref. {ref[5:]}/{ref[:4]})  →  '
                                     f'{self.cfg.get("email_contabilidade", "")}{ult}', fg=VERDE)
        else:
            self.lb_auto.config(text='✉  Envio automático desligado (ative em Configurações)' + ult, fg=SUAVE)

    # ---------- configuracoes ----------
    def abrir_config(self):
        j = tk.Toplevel(self); j.title('Configurações'); j.configure(bg=BG); j.resizable(False, False)
        j.transient(self); j.grab_set()
        try:
            j.iconbitmap(recurso('icone.ico'))
        except Exception:
            pass
        corpo = tk.Frame(j, bg=BG); corpo.pack(padx=24, pady=(18, 8))
        col_e = tk.Frame(corpo, bg=BG); col_e.grid(row=0, column=0, sticky='n', padx=(0, 28))
        col_d = tk.Frame(corpo, bg=BG); col_d.grid(row=0, column=1, sticky='n')
        campos = {}

        def secao(pai, texto):
            self._lbl(pai, texto, 11, AZUL, 'bold').pack(anchor='w', pady=(0, 2))

        def campo(pai, rot, chave, valor, dica='', procurar=None, senha=False):
            self._lbl(pai, rot, 8, SUAVE, 'bold').pack(anchor='w', pady=(10, 2))
            linha = tk.Frame(pai, bg=BG); linha.pack(anchor='w', fill='x')
            v = tk.StringVar(value=valor)
            en = tk.Entry(linha, textvariable=v, width=40 if procurar else 46, bg=CARD2, fg=TXT, relief='flat',
                          font=(FONTE, 10), insertbackground=TXT, highlightthickness=1, highlightbackground=LINHA,
                          highlightcolor=AZUL, show='•' if senha else '')
            en.pack(side='left', ipady=5)
            if procurar:
                Botao(linha, '…', lambda: procurar(v), cor=CARD2, hover=LINHA).pack(side='left', padx=(6, 0))
            if dica:
                self._lbl(pai, dica, 8, SUAVE, wraplength=380, justify='left').pack(anchor='w')
            campos[chave] = v

        def proc_banco(v):
            p = filedialog.askopenfilename(parent=j, title='Banco do PDV+', filetypes=[('Banco SQLite', '*.db'), ('Todos', '*.*')],
                                           initialdir=motor_pdv.PASTA_BANCO_PADRAO if os.path.isdir(motor_pdv.PASTA_BANCO_PADRAO) else None)
            if p: v.set(os.path.normpath(p))

        def proc_pasta(v):
            p = filedialog.askdirectory(parent=j, title='Escolha a pasta')
            if p: v.set(os.path.normpath(p))

        e = self.empresa
        secao(col_e, 'Empresa e arquivos')
        campo(col_e, 'TELEFONE DE CONTATO (obrigatório)', 'telefone', self.cfg.get('telefone') or e.get('fone', ''),
              'Com DDD, só números. Ex.: 32999949440')
        campo(col_e, 'NOME DO CONTATO', 'contato', self.cfg.get('contato', ''), 'Em branco = razão social')
        campo(col_e, 'BANCO DO PDV+', 'banco', self.cfg.get('banco', ''),
              'Padrão: C:\\PDV+\\.dart_tool\\sqflite_common_ffi\\databases\\navi_db.db', proc_banco)
        campo(col_e, 'PASTA PARA SALVAR OS ARQUIVOS', 'pasta', self.cfg.get('pasta') or pasta_documentos(), '', proc_pasta)
        campo(col_e, 'PASTA COM XMLs ORIGINAIS DE ENTRADA (opcional)', 'pasta_xml_originais',
              self.cfg.get('pasta_xml_originais', ''),
              'Se preenchida, os XMLs de entrada enviados à contabilidade saem dessa pasta (arquivos originais do '
              'fornecedor, com assinatura válida). Senão, saem do banco do PDV+.', proc_pasta)

        secao(col_d, 'E-mail e envio automático')
        campo(col_d, 'E-MAIL DA CONTABILIDADE', 'email_contabilidade', self.cfg.get('email_contabilidade', ''),
              'Mais de um? Separe com ponto e vírgula ( ; ).')
        campo(col_d, 'E-MAIL DO CLIENTE (Gmail que envia)', 'email_cliente', self.cfg.get('email_cliente', ''),
              'O e-mail sai desta conta e o cliente recebe uma cópia.')
        try:
            senha_atual = envio.revelar(self.cfg.get('senha_app', ''))
        except Exception:
            senha_atual = ''
        campo(col_d, 'SENHA DE APP DO GMAIL', 'senha_app', senha_atual,
              'Não é a senha normal do Gmail: é a senha de 16 letras criada em “Senhas de app” '
              '(exige verificação em duas etapas ativa).', senha=True)
        link = self._lbl(col_d, 'Abrir a página para criar a senha de app ↗', 9, AZUL, cursor='hand2')
        link.pack(anchor='w', pady=(4, 0))
        link.bind('<Button-1>', lambda ev: webbrowser.open('https://myaccount.google.com/apppasswords'))

        var_auto = tk.BooleanVar(value=bool(self.cfg.get('auto', True)))
        cx = tk.Checkbutton(col_d, text='Gerar e enviar automaticamente todo mês', variable=var_auto, bg=BG, fg=TXT,
                            selectcolor=CARD2, activebackground=BG, activeforeground=TXT, font=(FONTE, 10, 'bold'),
                            highlightthickness=0, bd=0)
        cx.pack(anchor='w', pady=(16, 0))
        self._lbl(col_d, 'A partir do dia 1º, ao ligar o computador, o SINTEGRA do mês anterior é gerado, salvo na '
                  'Área de Trabalho e enviado à contabilidade com os XMLs de entrada e saída e o relatório Excel.',
                  8, SUAVE, wraplength=380, justify='left').pack(anchor='w')

        var_ger = tk.BooleanVar(value=bool(self.cfg.get('enviar_ao_gerar', True)))
        tk.Checkbutton(col_d, text='Enviar à contabilidade ao clicar em “Gerar SINTEGRA”', variable=var_ger, bg=BG,
                       fg=TXT, selectcolor=CARD2, activebackground=BG, activeforeground=TXT, font=(FONTE, 10, 'bold'),
                       highlightthickness=0, bd=0).pack(anchor='w', pady=(14, 0))
        self._lbl(col_d, 'Mês já encerrado: envia na hora, sem perguntar. Mês ainda em andamento: pergunta antes e '
                  'envia como PARCIAL (o envio do dia 1º continua mandando o mês completo).',
                  8, SUAVE, wraplength=380, justify='left').pack(anchor='w')

        def coletar():
            tel = ''.join(ch for ch in campos['telefone'].get() if ch.isdigit())
            if len(tel) < 10:
                messagebox.showwarning('Telefone', 'Informe o telefone com DDD (10 ou 11 dígitos).', parent=j); return None
            banco = campos['banco'].get().strip()
            if not os.path.isfile(banco):
                messagebox.showwarning('Banco do PDV+', 'Arquivo do banco não encontrado.', parent=j); return None
            contab = envio.lista_emails(campos['email_contabilidade'].get())
            cliente = campos['email_cliente'].get().strip()
            senha = campos['senha_app'].get().replace(' ', '')
            for em in contab:
                if not envio.email_valido(em):
                    messagebox.showwarning('E-mail', f'E-mail da contabilidade inválido: {em}', parent=j); return None
            if cliente and not envio.email_valido(cliente):
                messagebox.showwarning('E-mail', 'E-mail do cliente inválido.', parent=j); return None
            if (var_auto.get() or var_ger.get()) and not (contab and cliente and senha):
                messagebox.showwarning('Envio automático', 'Para enviar à contabilidade, preencha o e-mail da '
                                       'contabilidade, o e-mail do cliente e a senha de app.', parent=j); return None
            return dict(telefone=tel, contato=campos['contato'].get().strip(), banco=banco,
                        pasta=campos['pasta'].get().strip() or pasta_documentos(),
                        pasta_xml_originais=campos['pasta_xml_originais'].get().strip(),
                        email_contabilidade='; '.join(contab), email_cliente=cliente, senha=senha, auto=var_auto.get(),
                        enviar_ao_gerar=var_ger.get())

        def testar():
            d = coletar()
            if not d: return
            if not (d['email_cliente'] and d['senha']):
                messagebox.showwarning('Testar e-mail', 'Preencha o e-mail do cliente e a senha de app.', parent=j); return
            j.config(cursor='watch'); j.update()
            try:
                envio.enviar(d['email_cliente'], d['senha'], [d['email_cliente']], [],
                             'Teste do Aliber SINTEGRA', 'Teste de envio do Aliber SINTEGRA: está funcionando.\n\n'
                             f'Os SINTEGRAs serão enviados para: {d["email_contabilidade"] or "(não configurado)"}', None, [])
                messagebox.showinfo('Testar e-mail', f'Tudo certo! Um e-mail de teste foi enviado para {d["email_cliente"]}.',
                                    parent=j)
            except envio.ErroEnvio as ex:
                messagebox.showerror('Testar e-mail', str(ex), parent=j)
            finally:
                j.config(cursor='')

        def salvar():
            d = coletar()
            if not d: return
            ligar_agora = d['auto'] and not self.cfg.get('auto')
            senha = d.pop('senha')
            self.cfg.update(d)
            self.cfg['senha_app'] = envio.proteger(senha)
            salvar_config(self.cfg)
            est = automatico.carregar_estado()
            if ligar_agora or (d['auto'] and 'inicio_auto' not in est):
                est['inicio_auto'] = automatico.mes_atual()   # primeiro envio automático: próximo dia 1º
                automatico.salvar_estado(est)
            ok = automatico.configurar_inicializacao(d['auto'])
            if sys.platform == 'win32' and not ok:
                messagebox.showwarning('Envio automático', 'Não consegui registrar o programa para iniciar com o '
                                       'Windows. Veja o arquivo de log em ' + APP_DIR, parent=j)
            try:
                self.empresa = motor_pdv.dados_empresa(d['banco'])
            except Exception:
                registrar_erro(traceback.format_exc())
                messagebox.showerror('Banco do PDV+', 'Não consegui ler esse arquivo como banco do PDV+.', parent=j); return
            self._mostrar_empresa(); j.destroy()

        rod = tk.Frame(j, bg=BG); rod.pack(fill='x', padx=24, pady=(10, 20))
        Botao(rod, 'Testar e-mail', testar, cor=CARD2, hover=LINHA).pack(side='left')
        Botao(rod, '🔒  Escolher versão', lambda: self.pedir_senha_tecnico(j), cor=CARD2, hover=LINHA).pack(
            side='left', padx=8)
        Botao(rod, 'Salvar', salvar).pack(side='right')
        Botao(rod, 'Cancelar', j.destroy, cor=CARD2, hover=LINHA).pack(side='right', padx=8)

    # ---------- geracao ----------
    def gerar(self):
        if not self.cfg.get('telefone') or not self.cfg.get('banco'):
            self.abrir_config(); return
        mm, aaaa = self.cb_mes.get().split('/')
        periodo = f'{aaaa}-{mm}'
        pasta = os.path.join(self.cfg.get('pasta') or pasta_documentos(), periodo)
        os.makedirs(pasta, exist_ok=True)
        self.bt_gerar.habilitar(False); self.bt_pasta.habilitar(False); self.bt_rel.habilitar(False)
        self.bt_enviar.habilitar(False)
        self.lb_status.config(text=f'Gerando o SINTEGRA de {mm}/{aaaa}…', fg=AZUL)
        self.lb_arquivo.config(text='Lendo o banco do PDV+ e montando SINTEGRA, XMLs e relatório Excel '
                                    '(o caixa pode continuar aberto).')
        fin = FINALIDADES[self.cb_fin.get()]

        def tarefa():
            try:
                r = motor_pdv.gerar(self.cfg['banco'], periodo, self.cfg['telefone'], pasta,
                                    self.cfg.get('contato') or None, fin, self.cfg.get('pasta_xml_originais') or None)
                r['relatorio'] = r['arquivos'].get('excel') or r['arquivos'].get('conferencia')
                self.fila.put(('ok', r, pasta, periodo))
            except Exception:
                tb = traceback.format_exc(); registrar_erro(tb)
                self.fila.put(('erro', tb, pasta, periodo))

        threading.Thread(target=tarefa, daemon=True).start()
        self.after(100, self._esperar)

    def _esperar(self):
        try:
            tipo, r, pasta, periodo = self.fila.get_nowait()
        except queue.Empty:
            self.after(100, self._esperar); return
        self.bt_gerar.habilitar(True)
        self.ultimo = dict(pasta=pasta, relatorio=r.get('relatorio') if isinstance(r, dict) else None,
                           r=r if isinstance(r, dict) else None)
        if tipo == 'erro':
            self.lb_status.config(text='Não foi possível gerar o arquivo.', fg=VERMELHO_HOVER)
            self.lb_arquivo.config(text='O erro foi registrado em ' + os.path.join(APP_DIR, 'erros.log'))
            self._avisos([('erro', r.strip().splitlines()[-1])])
            return
        self._mostrar(r, periodo)
        if self.cfg.get('enviar_ao_gerar', True) and r.get('arquivo'):
            if self._email_configurado():
                self.after(300, lambda: self.enviar_contabilidade(apos_gerar=True))
            else:
                self.lb_status.config(text=self.lb_status.cget('text') + '  ·  não enviado (e-mail não configurado)')

    def _mostrar(self, r, periodo):
        d, v, cf = r['documentos'], r['valores'], r['conferencia']
        self.tile['ent'][0].config(text=str(d.get('NF-e entrada', 0)))
        self.tile['ent'][1].config(text=f'R$ {br(v.get("NF-e entrada", 0))}')
        self.tile['nfce'][0].config(text=str(d.get('NFC-e autorizada', 0)))
        self.tile['nfce'][1].config(text=f'R$ {br(v.get("NFC-e", 0))}')
        self.tile['nfe'][0].config(text=str(d.get('NF-e saida', 0)))
        self.tile['nfe'][1].config(text=f'R$ {br(v.get("NF-e saida", 0))}')
        canc = d.get('NFC-e cancelada', 0) + d.get('NF-e cancelada', 0)
        self.tile['canc'][0].config(text=str(canc))
        self.tile['canc'][1].config(text=f'{d.get("NFC-e cancelada", 0)} NFC-e · {d.get("NF-e cancelada", 0)} NF-e')

        itens = [('erro', 'ERRO: ' + x) for x in r['erros']]
        todos = motor_pdv.avisos_usuario(r)
        ipi = [x.split(':')[0].replace('NF-e ', '') for x in todos if 'registro 51 (IPI)' in x]
        itens += [('aviso', aviso_amigavel(x)) for x in todos if 'registro 51 (IPI)' not in x]
        if ipi:
            itens.append(('aviso', f'{len(ipi)} NF-e de entrada com IPI destacado pelo fornecedor ({", ".join(ipi)}). '
                                   'O registro 51 (IPI) não é gerado; normalmente só é exigido de contribuinte '
                                   'do IPI. Confirme com a contabilidade.'))
        mm, aaaa = periodo[5:], periodo[:4]
        if r['erros'] or not r['arquivo']:
            self.lb_status.config(text=f'✗  SINTEGRA {mm}/{aaaa} com erros — não envie à contabilidade', fg=VERMELHO_HOVER)
        elif itens:
            self.lb_status.config(text=f'✓  SINTEGRA {mm}/{aaaa} gerado — leia os avisos abaixo', fg=AMARELO)
        else:
            self.lb_status.config(text=f'✓  SINTEGRA {mm}/{aaaa} gerado', fg=VERDE)
        self.lb_arquivo.config(text=(f'Pasta: {os.path.dirname(r["arquivo"])}   ·   SINTEGRA, relatório Excel, '
                                     f'XMLs de entrada e de saída' if r['arquivo'] else ''))
        if r.get('conferencia_ok'):
            self.lb_conf.config(text='✓  Conferência com o banco do PDV+: quantidades e valores batem', fg=VERDE)
        else:
            self.lb_conf.config(text='⚠  Conferência com o banco do PDV+: há divergência (veja o relatório)', fg=AMARELO)
        self._avisos(itens or [('', 'Nenhum aviso.')])
        self.bt_pasta.habilitar(True); self.bt_rel.habilitar(bool(r['arquivos'].get('excel')))
        self.bt_enviar.habilitar(bool(r['arquivos'].get('sintegra')))

    def _avisos(self, itens):
        t = self.tx_avisos
        t.configure(state='normal'); t.delete('1.0', 'end')
        for tag, texto in itens:
            t.insert('end', '•  ' + texto + '\n\n', tag)
        t.configure(state='disabled')

    def _email_configurado(self):
        return bool(envio.lista_emails(self.cfg.get('email_contabilidade')) and self.cfg.get('email_cliente')
                    and self.cfg.get('senha_app'))

    def enviar_contabilidade(self, apos_gerar=False):
        r = self.ultimo and self.ultimo.get('r')
        if not r:
            return
        para = envio.lista_emails(self.cfg.get('email_contabilidade'))
        if not self._email_configurado():
            messagebox.showinfo('Enviar', 'Configure o e-mail da contabilidade, o e-mail do cliente e a senha de '
                                'app em Configurações.', parent=self)
            self.abrir_config(); return
        p = r['periodo']
        hoje = date.today()
        parcial = p >= automatico.mes_atual(hoje)   # mês ainda não terminou
        bloq = motor_pdv.problemas_bloqueantes(r)
        enviados = automatico.carregar_estado().get('enviados', {})
        destino = f'{", ".join(para)}\n\n(cópia para {self.cfg["email_cliente"]})'
        perguntar = not apos_gerar or bool(bloq) or p in enviados or parcial
        if perguntar:
            if parcial:
                pergunta = (f'{p[5:]}/{p[:4]} AINDA NÃO TERMINOU (hoje é {hoje:%d/%m/%Y}).\n\n'
                            f'O arquivo tem só o movimento até agora. Ele será enviado como PARCIAL e o envio do '
                            f'dia 1º continuará mandando o mês completo.\n\nEnviar a parcial para:\n\n{destino}')
            else:
                pergunta = f'Enviar o SINTEGRA {p[5:]}/{p[:4]}, os XMLs e o relatório Excel para:\n\n{destino}'
            if bloq:
                pergunta = 'ATENÇÃO: ' + '; '.join(bloq) + '.\n\n' + pergunta + '\n\nEnviar mesmo assim?'
            if p in enviados and not parcial:
                pergunta = f'Esse mês já foi enviado em {enviados[p]["data"]}.\n\n' + pergunta
            if not messagebox.askyesno('Enviar para a contabilidade', pergunta, parent=self):
                if apos_gerar:
                    self.lb_status.config(text=self.lb_status.cget('text') + '  ·  não enviado')
                return
        self.bt_enviar.habilitar(False); self.bt_gerar.habilitar(False)
        self.lb_status.config(text=f'Enviando o SINTEGRA {p[5:]}/{p[:4]} para a contabilidade…', fg=AZUL)

        def tarefa():
            try:
                assunto, texto, html, anexos = envio.montar_email_contabilidade(r, r['empresa'], automatico=False)
                if parcial:
                    nota = (f'ATENÇÃO: ARQUIVO PARCIAL - {p[5:]}/{p[:4]} ainda não terminou; movimento até '
                            f'{hoje:%d/%m/%Y}. O arquivo do mês completo será enviado no início do próximo mês.')
                    assunto = '[PARCIAL] ' + assunto
                    texto = nota + '\n\n' + texto
                    html = (f'<div style="font-family:Arial,sans-serif;background:#FFF4D6;border:1px solid #F2B33D;'
                            f'padding:10px 14px;margin-bottom:14px;font-size:13px"><b>{nota}</b></div>' + html)
                n = envio.enviar(self.cfg['email_cliente'], envio.revelar(self.cfg['senha_app']), para,
                                 envio.lista_emails(self.cfg['email_cliente']), assunto, texto, html, anexos)
                if not parcial:
                    automatico.marcar_enviado(p, automatico=False)
                msg = (f'{"Parcial enviada" if parcial else "Enviado"} para {", ".join(para)}'
                       + (f' em {n} e-mails (anexos grandes)' if n > 1 else '') + '.')
                self.after(0, lambda: self._enviado(True, msg, parcial))
            except envio.ErroEnvio as ex:
                msg = str(ex)
                self.after(0, lambda: self._enviado(False, msg))
            except Exception:
                tb = traceback.format_exc(); registrar_erro(tb)
                self.after(0, lambda: self._enviado(False, tb.strip().splitlines()[-1]))

        threading.Thread(target=tarefa, daemon=True).start()

    def _enviado(self, ok, msg, parcial=False):
        self.bt_enviar.habilitar(True); self.bt_gerar.habilitar(True)
        p = self.ultimo['r']['periodo']
        if ok:
            self.lb_status.config(text=f'✓  SINTEGRA {p[5:]}/{p[:4]} {"(PARCIAL) " if parcial else ""}'
                                       f'enviado para a contabilidade', fg=AMARELO if parcial else VERDE)
            messagebox.showinfo('Enviado', msg, parent=self)
        else:
            self.lb_status.config(text='✗  O envio falhou', fg=VERMELHO_HOVER)
            messagebox.showerror('Envio', msg, parent=self)
        self._mostrar_auto()

    def abrir_simulacao(self):
        if not (self.cfg.get('telefone') and self.cfg.get('email_cliente') and self.cfg.get('senha_app')):
            messagebox.showinfo('Simular envio automático', 'Preencha e salve as Configurações (telefone, e-mail do '
                                'cliente e senha de app) antes de simular.', parent=self)
            self.abrir_config(); return
        j = tk.Toplevel(self); j.title('Simular envio automático'); j.configure(bg=BG); j.resizable(False, False)
        j.transient(self); j.grab_set()
        try:
            j.iconbitmap(recurso('icone.ico'))
        except Exception:
            pass
        corpo = tk.Frame(j, bg=BG); corpo.pack(padx=26, pady=(20, 6))
        self._lbl(corpo, 'Simular envio automático', 13, AZUL, 'bold').pack(anchor='w')
        hoje = date.today()
        prox = date(hoje.year + (hoje.month == 12), hoje.month % 12 + 1, 1)
        self._lbl(corpo, 'DATA A SIMULAR (dd/mm/aaaa)', 8, SUAVE, 'bold').pack(anchor='w', pady=(14, 2))
        v = tk.StringVar(value=prox.strftime('%d/%m/%Y'))
        tk.Entry(corpo, textvariable=v, width=14, bg=CARD2, fg=TXT, relief='flat', font=(FONTE, 12),
                 insertbackground=TXT, highlightthickness=1, highlightbackground=LINHA, highlightcolor=AZUL).pack(
            anchor='w', ipady=5)
        info = self._lbl(corpo, '', 9, TXT, wraplength=470, justify='left'); info.pack(anchor='w', pady=(12, 0))

        def atualizar(*_):
            d = ler_data(v.get())
            if not d:
                info.config(text='Data inválida.', fg=VERMELHO_HOVER); return
            ref = automatico.mes_anterior(d)
            info.config(fg=TXT, text=(
                f'O programa vai agir como se hoje fosse {d:%d/%m/%Y} e o computador tivesse acabado de ligar:\n\n'
                f'•  gera o SINTEGRA de {ref[5:]}/{ref[:4]}, o relatório Excel e os XMLs;\n'
                f'•  copia para a Área de Trabalho como TESTE-SINTEGRA-….TXT;\n'
                f'•  envia o e-mail SÓ para {self.cfg.get("email_cliente")} (a contabilidade não recebe);\n'
                f'•  mostra o aviso no canto da tela, como no dia 1º.\n\n'
                'O relógio do Windows, o PDV+ e o controle de envios NÃO são alterados.'))
        v.trace_add('write', atualizar); atualizar()

        def iniciar():
            d = ler_data(v.get())
            if not d:
                return
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable, '--automatico', '--simular', d.isoformat()]
            else:
                cmd = [sys.executable, os.path.abspath(__file__), '--automatico', '--simular', d.isoformat()]
            try:
                subprocess.Popen(cmd, cwd=os.path.dirname(os.path.abspath(
                    sys.executable if getattr(sys, 'frozen', False) else __file__)))
            except Exception:
                registrar_erro(traceback.format_exc())
                messagebox.showerror('Simular', 'Não consegui iniciar a simulação.', parent=j); return
            j.destroy()
            messagebox.showinfo('Simulação iniciada', 'A simulação está rodando em segundo plano. Em cerca de 1 '
                                'minuto aparece o aviso no canto da tela e chega o e-mail de teste.', parent=self)

        rod = tk.Frame(j, bg=BG); rod.pack(fill='x', padx=26, pady=(14, 20))
        Botao(rod, 'Iniciar simulação', iniciar).pack(side='right')
        Botao(rod, 'Cancelar', j.destroy, cor=CARD2, hover=LINHA).pack(side='right', padx=8)

    # ---------- troca de versao (tecnico) ----------
    def _janela(self, pai, titulo):
        j = tk.Toplevel(pai); j.title(titulo); j.configure(bg=BG); j.resizable(False, False)
        j.transient(pai); j.grab_set()
        try:
            j.iconbitmap(recurso('icone.ico'))
        except Exception:
            pass
        return j

    def pedir_senha_tecnico(self, pai):
        j = self._janela(pai, 'Área do técnico')
        corpo = tk.Frame(j, bg=BG); corpo.pack(padx=26, pady=(20, 6))
        self._lbl(corpo, 'Escolher versão', 13, AZUL, 'bold').pack(anchor='w')
        self._lbl(corpo, 'Área do técnico da Aliber. Digite a senha do técnico.', 9, SUAVE).pack(anchor='w', pady=(2, 10))
        v = tk.StringVar()
        en = tk.Entry(corpo, textvariable=v, show='•', width=30, bg=CARD2, fg=TXT, relief='flat', font=(FONTE, 12),
                      insertbackground=TXT, highlightthickness=1, highlightbackground=LINHA, highlightcolor=AZUL)
        en.pack(anchor='w', ipady=5); en.focus_set()
        msg = self._lbl(corpo, '', 9, VERMELHO_HOVER); msg.pack(anchor='w', pady=(6, 0))

        def entrar(*_):
            try:
                ok = versoes.conferir_senha(v.get())
            except versoes.ErroVersao as e:
                msg.config(text=str(e)); return
            if not ok:
                msg.config(text='Senha incorreta.'); v.set(''); return
            j.destroy()
            self.abrir_versoes(pai)

        en.bind('<Return>', entrar)
        rod = tk.Frame(j, bg=BG); rod.pack(fill='x', padx=26, pady=(10, 20))
        Botao(rod, 'Entrar', entrar).pack(side='right')
        Botao(rod, 'Cancelar', j.destroy, cor=CARD2, hover=LINHA).pack(side='right', padx=8)

    def abrir_versoes(self, pai):
        j = self._janela(pai, 'Escolher versão')
        corpo = tk.Frame(j, bg=BG); corpo.pack(padx=24, pady=(18, 6), fill='both')
        self._lbl(corpo, 'Escolher versão', 13, AZUL, 'bold').pack(anchor='w')
        self._lbl(corpo, f'Versão instalada: {VERSAO}', 9, SUAVE).pack(anchor='w', pady=(2, 10))
        lista = tk.Listbox(corpo, width=62, height=7, bg=CARD2, fg=TXT, relief='flat', font=(FONTE, 10),
                           selectbackground=AZUL, selectforeground='white', highlightthickness=0, activestyle='none')
        lista.pack(anchor='w', fill='x')
        self._lbl(corpo, 'O QUE MUDOU', 8, SUAVE, 'bold').pack(anchor='w', pady=(12, 4))
        notas = tk.Text(corpo, width=62, height=9, bg=CARD2, fg=TXT, relief='flat', wrap='word', font=(FONTE, 9),
                        padx=10, pady=8, highlightthickness=0)
        notas.pack(anchor='w', fill='x'); notas.configure(state='disabled')
        status = self._lbl(corpo, 'Buscando as versões publicadas…', 9, SUAVE, wraplength=520, justify='left')
        status.pack(anchor='w', pady=(10, 0))
        itens, cache_notas = [], {}
        rod = tk.Frame(j, bg=BG); rod.pack(fill='x', padx=24, pady=(10, 20))
        bt = Botao(rod, 'Instalar esta versão', lambda: instalar())
        bt.pack(side='right'); bt.habilitar(False)
        Botao(rod, 'Fechar', j.destroy, cor=CARD2, hover=LINHA).pack(side='right', padx=8)

        def mostrar_notas(texto):
            notas.configure(state='normal'); notas.delete('1.0', 'end')
            notas.insert('end', texto or '(sem notas para esta versão)'); notas.configure(state='disabled')

        def selecionou(*_):
            sel = lista.curselection()
            if not sel:
                return
            it = itens[sel[0]]
            bt.habilitar(not it['instalada'])
            if it['versao'] in cache_notas:
                mostrar_notas(cache_notas[it['versao']]); return
            mostrar_notas('Carregando…')

            def t():
                cache_notas[it['versao']] = versoes.notas(it)
                self.after(0, lambda: lista.curselection() and itens[lista.curselection()[0]] is it
                           and mostrar_notas(cache_notas[it['versao']]))
            threading.Thread(target=t, daemon=True).start()

        lista.bind('<<ListboxSelect>>', selecionou)

        def carregou(res):
            if isinstance(res, Exception):
                status.config(text=str(res), fg=VERMELHO_HOVER); return
            itens[:] = res
            for it in res:
                rot = f'  Versão {it["versao"]}   ·   {it["tamanho"] / 1048576:.1f} MB'
                if it['instalada']:
                    rot += '   ·   INSTALADA'
                elif it['mais_antiga']:
                    rot += '   ·   mais antiga'
                lista.insert('end', rot)
            status.config(text=f'{len(res)} versão(ões) publicada(s). Selecione uma para ver o que mudou.' if res
                          else 'Nenhuma versão publicada encontrada.', fg=SUAVE)
            if res:
                lista.selection_set(0); selecionou()

        def buscar():
            try:
                r = versoes.listar(VERSAO)
            except versoes.ErroVersao as e:
                r = e
            except Exception as e:
                registrar_erro(traceback.format_exc()); r = Exception(f'Erro ao buscar versões: {e}')
            self.after(0, lambda: carregou(r))
        threading.Thread(target=buscar, daemon=True).start()

        def instalar():
            sel = lista.curselection()
            if not sel:
                return
            it = itens[sel[0]]
            aviso = f'Instalar a versão {it["versao"]}?\n\nO Aliber SINTEGRA será fechado, atualizado e aberto de novo. ' \
                    'As configurações, a senha do Gmail e o histórico de envios são mantidos.'
            if it['mais_antiga']:
                aviso = f'A versão {it["versao"]} é MAIS ANTIGA que a instalada ({VERSAO}).\n\n' + aviso
            if it['sem_seletor']:
                aviso += f'\n\nATENÇÃO: a versão {it["versao"]} não tem esta tela de troca de versão. Para voltar ' \
                         'depois, será preciso rodar o instalador da versão nova manualmente.'
            if not messagebox.askyesno('Escolher versão', aviso, parent=j):
                return
            bt.habilitar(False)

            def t():
                try:
                    caminho = versoes.baixar(it, lambda p: self.after(0, lambda: status.config(
                        text=f'Baixando a versão {it["versao"]}… {p}%', fg=AZUL)))
                    self.after(0, lambda: status.config(text='Instalando… o programa vai fechar e abrir de novo.',
                                                        fg=AZUL))
                    versoes.instalar(caminho)
                    self.after(1500, self.destroy)
                except versoes.ErroVersao as e:
                    m = str(e); self.after(0, lambda: (status.config(text=m, fg=VERMELHO_HOVER), bt.habilitar(True)))
                except Exception as e:
                    registrar_erro(traceback.format_exc()); m = f'Erro ao instalar: {e}'
                    self.after(0, lambda: (status.config(text=m, fg=VERMELHO_HOVER), bt.habilitar(True)))
            threading.Thread(target=t, daemon=True).start()

    def abrir_pasta(self):
        if self.ultimo: abrir(self.ultimo['pasta'])

    def abrir_relatorio(self):
        if self.ultimo and self.ultimo.get('relatorio'): abrir(self.ultimo['relatorio'])


def ler_data(txt):
    from datetime import datetime
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime((txt or '').strip(), fmt).date()
        except ValueError:
            pass
    return None


def main():
    if '--automatico' in sys.argv:
        simulada = None
        if '--simular' in sys.argv:
            i = sys.argv.index('--simular')
            simulada = ler_data(sys.argv[i + 1]) if i + 1 < len(sys.argv) else None
            if not simulada:
                automatico.log('[TESTE] Data inválida em --simular'); return
        try:
            automatico.rodar_em_segundo_plano(carregar_config(), hoje=simulada)
        except Exception:
            automatico.log('Falha geral: ' + traceback.format_exc())
        return
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()


if __name__ == '__main__':
    main()

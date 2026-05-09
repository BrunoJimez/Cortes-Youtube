#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cortador de Vídeos - TikTok / Instagram
=======================================

Funcionalidades:
- Corte por duração fixa OU por número de partes (com lógica matemática garantindo soma exata).
- Ajuste de proporção: 9:16, 16:9, 1:1, 4:5 (com fundo borrado para preencher).
- Música de fundo com sidechain ducking (a música abaixa automaticamente
  quando há voz/áudio principal e volta quando não há - profissional).
- Múltiplas músicas em rotação: ao adicionar várias faixas, cada corte recebe
  uma; quando a lista termina, volta para a primeira (rotação cíclica).
- Botão "Parar" cancela a operação em andamento (mata o FFmpeg atual e remove
  o arquivo parcial).
- Aceita qualquer formato suportado pelo FFmpeg (mp4, mov, mkv, avi, webm, etc.).
- Interface gráfica simples (Tkinter - já vem com o Python).

Requer: Python 3.8+ e FFmpeg instalado no PATH.
"""

import os
import re
import sys
import json
import shutil
import subprocess
import threading
from pathlib import Path
from tkinter import (
    Tk, StringVar, IntVar, DoubleVar, BooleanVar,
    Listbox, END, SINGLE,
    filedialog, messagebox, ttk
)
from tkinter.scrolledtext import ScrolledText


APP_TITLE = "Cortador de Vídeos - TikTok / Instagram"
APP_VERSION = "1.1"

# Mapa de proporções: rótulo -> (largura, altura) em pixels
ASPECT_RATIOS = {
    "Original (manter como está)":           None,
    "9:16 - TikTok / Reels / Shorts":        (1080, 1920),
    "16:9 - YouTube / Horizontal":           (1920, 1080),
    "1:1 - Instagram Feed (quadrado)":       (1080, 1080),
    "4:5 - Instagram Retrato":               (1080, 1350),
}

VIDEO_EXTENSIONS = [
    ("Vídeos", "*.mp4 *.mov *.avi *.mkv *.webm *.flv *.wmv *.m4v *.mpg *.mpeg *.ts *.3gp"),
    ("Todos os arquivos", "*.*"),
]
AUDIO_EXTENSIONS = [
    ("Áudios", "*.mp3 *.wav *.aac *.m4a *.ogg *.flac *.wma *.opus"),
    ("Todos os arquivos", "*.*"),
]


# =====================================================================
# BACKEND - Funções de processamento (sem GUI)
# =====================================================================

def find_ffmpeg():
    """Procura ffmpeg/ffprobe no PATH e em locais comuns no Windows."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if (not ffmpeg or not ffprobe) and sys.platform == "win32":
        candidates = [
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
            os.path.expanduser(r"~\ffmpeg\bin"),
        ]
        for d in candidates:
            fexe = os.path.join(d, "ffmpeg.exe")
            pexe = os.path.join(d, "ffprobe.exe")
            if os.path.exists(fexe) and os.path.exists(pexe):
                ffmpeg = ffmpeg or fexe
                ffprobe = ffprobe or pexe
                break
    return ffmpeg, ffprobe


def get_video_info(path, ffprobe):
    """
    Retorna (duracao_segundos, largura, altura, tem_audio).
    Lança RuntimeError em caso de falha.
    """
    cmd = [
        ffprobe, "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe falhou:\n{result.stderr}")

    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])

    width = height = 0
    has_audio = False
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and width == 0:
            width = int(s.get("width", 0))
            height = int(s.get("height", 0))
        elif s.get("codec_type") == "audio":
            has_audio = True
    return duration, width, height, has_audio


def calc_segments_by_duration(total, target):
    """
    Modo 1: Você informa o tamanho desejado de cada corte.
        qtd  = floor(T / d)
        resto = T - qtd*d
    Gera 'qtd' cortes de 'd' segundos. Se houver 'resto' significativo,
    adiciona 1 corte final com a duração 'resto'.

    Restos menores que 0.3s são descartados (não vale a pena gerar
    um arquivo minúsculo).
    """
    if target <= 0:
        return []
    qtd = int(total // target)
    resto = total - (qtd * target)
    segments = [float(target)] * qtd
    if resto >= 0.3:
        segments.append(resto)
    return segments


def calc_segments_by_parts(total, n):
    """
    Modo 2: Você informa em quantas partes dividir.
        base  = floor(T / n)
        resto = T % n
        Os primeiros 'resto' cortes recebem base+1, os demais base.
    Garante soma final == T.

    Trabalha em segundos inteiros (como o enunciado pediu), e
    qualquer fração residual de T (ex: T=60.5) é somada no último
    corte para preservar a duração total exata.

    Exemplo T=60, n=7 → [9, 9, 9, 9, 8, 8, 8]  (soma=60).
    Exemplo T=207, n=5 → [42, 42, 41, 41, 41]  (soma=207).
    """
    if n < 1:
        return []
    total_int = int(total)         # parte inteira (segundos cheios)
    frac = total - total_int       # eventual fração residual

    base = total_int // n
    resto = total_int % n
    segs = [float(base + 1)] * resto + [float(base)] * (n - resto)

    if frac > 0 and segs:
        segs[-1] += frac           # joga a fração no último corte

    # Remove segmentos vazios/insignificantes (caso n > T)
    segs = [s for s in segs if s >= 0.3]
    return segs


def sanitize_filename(name):
    """Remove caracteres inválidos para nomes de arquivo em Windows/Linux/Mac."""
    name = re.sub(r'[<>:"/\\|?*\n\r\t]', '_', name)
    name = name.strip(" .")
    return name or "video"


def build_filter_complex(aspect, has_music, music_volume, has_audio, duration):
    """
    Monta o filter_complex do FFmpeg combinando:
      - Ajuste de proporção (com fundo borrado preenchendo as bordas)
      - Mixagem de áudio com sidechain ducking quando há música

    Retorna (filter_string, video_map, audio_map_or_None)
    """
    filters = []

    # ---------- VÍDEO ----------
    if aspect is None:
        # Mantém vídeo como está, só padroniza framerate
        filters.append("[0:v]fps=30,setsar=1[v]")
    else:
        tw, th = aspect
        # Estratégia "blur fill": duplica o vídeo, escala uma cópia
        # para preencher (cropando) e desfoca -> usa como fundo;
        # sobrepõe a versão original escalada proporcionalmente no centro.
        # Resultado: vídeo nunca fica esticado, e as bordas (laterais ou
        # superior/inferior) ficam bonitas com um fundo desfocado.
        filters.append(
            f"[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},gblur=sigma=20[bg];"
            f"[fgsrc]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps=30,setsar=1[v]"
        )
    video_map = "[v]"

    # ---------- ÁUDIO ----------
    if has_music and has_audio:
        # Mixagem profissional: sidechain ducking
        # 1) Aplica volume base na música
        # 2) Divide o áudio principal (voz) em duas vias: uma vai pro mix
        #    final, outra serve de "trigger" para abaixar a música
        # 3) sidechaincompress: quando a voz toca, a música abaixa automaticamente
        # 4) amix: combina voz + música (com ducking aplicado)
        af = (
            f"[1:a]volume={music_volume:.3f},"
            f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[mvol];"
            f"[0:a]asplit=2[voice1][voice_sc];"
            f"[mvol][voice_sc]sidechaincompress="
            f"threshold=0.04:ratio=6:attack=10:release=350:makeup=1[mduck];"
            f"[voice1][mduck]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[aout]"
        )
        filters.append(af)
        audio_map = "[aout]"
    elif has_music and not has_audio:
        # Só música (vídeo sem áudio original)
        af = (
            f"[1:a]volume={min(music_volume * 2, 1.0):.3f},"
            f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[aout]"
        )
        filters.append(af)
        audio_map = "[aout]"
    elif has_audio:
        # Só áudio original
        audio_map = "0:a"
    else:
        audio_map = None  # Sem áudio nenhum

    return ";".join(filters), video_map, audio_map


def process_segment(ffmpeg, input_video, start, duration, output_path,
                    aspect_key, music_path, music_volume, has_audio, log,
                    token=None):
    """
    Processa um único segmento: corte + proporção + mixagem em uma só passada.

    Se 'token' for fornecido (CancelToken), permite cancelamento: o processo
    FFmpeg é registrado no token para que possa ser morto externamente, e ao
    detectar cancelamento o arquivo de saída parcial é removido.
    """
    aspect = ASPECT_RATIOS.get(aspect_key)
    has_music = bool(music_path) and Path(music_path).exists()

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
        "-ss", f"{start:.3f}",
        "-i", str(input_video),
    ]

    if has_music:
        # -stream_loop -1 faz a música repetir indefinidamente caso
        # ela seja mais curta que o segmento
        cmd.extend(["-stream_loop", "-1", "-i", str(music_path)])

    filter_str, vmap, amap = build_filter_complex(
        aspect, has_music, music_volume, has_audio, duration
    )

    if filter_str:
        cmd.extend(["-filter_complex", filter_str])

    cmd.extend(["-map", vmap])
    if amap:
        cmd.extend(["-map", amap])

    # -t como OUTPUT option (depois dos -map): garante a duração correta
    # mesmo quando há input em loop infinito (música).
    cmd.extend(["-t", f"{duration:.3f}"])

    # Codec de vídeo: H.264 yuv420p é o mais compatível com TikTok/Instagram
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", "30",
    ])

    if amap:
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000"])

    cmd.extend([
        "-movflags", "+faststart",
        str(output_path),
    ])

    log(f"\n→ Gerando: {Path(output_path).name}")

    # Em Windows, criar grupo de processo separado permite matar o ffmpeg
    # de forma limpa sem afetar o processo Python pai.
    popen_kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except FileNotFoundError as e:
        log(f"❌ ERRO: ffmpeg não encontrado ({e})")
        return False

    if token is not None:
        token.set_proc(proc)

    try:
        _, stderr = proc.communicate()
    finally:
        if token is not None:
            token.set_proc(None)

    # Cancelado pelo usuário?
    if token is not None and token.is_cancelled():
        log(f"⏹  Cancelado: {Path(output_path).name}")
        # Remove arquivo parcial para não deixar lixo
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except OSError:
            pass
        return False

    if proc.returncode != 0:
        err = (stderr or "")[-1500:]
        log(f"❌ ERRO no FFmpeg:\n{err}")
        return False
    log(f"✔ OK: {Path(output_path).name}")
    return True


# =====================================================================
# Cancelamento
# =====================================================================

class CancelToken:
    """
    Permite que a UI cancele a operação de processamento em andamento.

    - .cancel():        marca o cancelamento e mata o ffmpeg ativo (se houver)
    - .is_cancelled():  consulta o estado (usado nos pontos de verificação)
    - .set_proc(p):     a função de processamento registra o subprocess ativo
                        para que cancel() saiba o que matar
    - .reset():         limpa o estado para uma nova operação
    """
    def __init__(self):
        self._event = threading.Event()
        self._proc = None
        self._lock = threading.Lock()

    def cancel(self):
        self._event.set()
        with self._lock:
            p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
            # Pequena espera; se não morrer, força
            try:
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def is_cancelled(self):
        return self._event.is_set()

    def set_proc(self, proc):
        with self._lock:
            self._proc = proc

    def reset(self):
        self._event.clear()
        with self._lock:
            self._proc = None


# =====================================================================
# GUI
# =====================================================================

class App:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP_TITLE} v{APP_VERSION}")
        root.geometry("820x800")
        root.minsize(740, 680)

        # Variáveis de estado
        self.video_path = StringVar()
        self.output_dir = StringVar()

        # Música: agora suportamos múltiplas faixas em rotação.
        # self.music_files guarda os caminhos completos; a Listbox da UI
        # mostra apenas os nomes (basenames).
        self.music_files = []
        self.music_volume = DoubleVar(value=20.0)  # %
        self.use_music = BooleanVar(value=False)

        self.mode = StringVar(value="duration")     # 'duration' ou 'parts'
        self.duration_value = StringVar(value="60")  # segundos
        self.parts_value = StringVar(value="7")

        self.aspect = StringVar(value="9:16 - TikTok / Reels / Shorts")

        self.ffmpeg = None
        self.ffprobe = None

        # Cancelamento
        self.cancel_token = CancelToken()
        self.is_running = False

        # Tratar fechamento da janela
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._check_ffmpeg()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # ---- 1. Vídeo ----
        f1 = ttk.LabelFrame(self.root, text="1. Vídeo de Entrada")
        f1.pack(fill="x", padx=10, pady=(10, 5))
        inner1 = ttk.Frame(f1); inner1.pack(fill="x", **pad)
        ttk.Entry(inner1, textvariable=self.video_path).pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(inner1, text="Selecionar...", command=self._pick_video).pack(side="right")

        # ---- 2. Pasta de saída ----
        f2 = ttk.LabelFrame(self.root, text="2. Pasta de Saída")
        f2.pack(fill="x", padx=10, pady=5)
        inner2 = ttk.Frame(f2); inner2.pack(fill="x", **pad)
        ttk.Entry(inner2, textvariable=self.output_dir).pack(
            side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(inner2, text="Selecionar...", command=self._pick_output).pack(side="right")

        # ---- 3. Modo de corte ----
        f3 = ttk.LabelFrame(self.root, text="3. Modo de Corte")
        f3.pack(fill="x", padx=10, pady=5)

        row1 = ttk.Frame(f3); row1.pack(fill="x", **pad)
        ttk.Radiobutton(row1, text="Por DURAÇÃO de cada corte (segundos):",
                        variable=self.mode, value="duration").pack(side="left")
        ttk.Entry(row1, textvariable=self.duration_value, width=10).pack(side="left", padx=8)
        ttk.Label(row1, text="ex: 60 = 1 min  |  180 = 3 min",
                  foreground="#666").pack(side="left")

        row2 = ttk.Frame(f3); row2.pack(fill="x", **pad)
        ttk.Radiobutton(row2, text="Em N PARTES iguais:",
                        variable=self.mode, value="parts").pack(side="left")
        ttk.Entry(row2, textvariable=self.parts_value, width=10).pack(side="left", padx=8)
        ttk.Label(row2, text="ex: 7 = 7 partes (resto distribuído)",
                  foreground="#666").pack(side="left")

        # ---- 4. Proporção ----
        f4 = ttk.LabelFrame(self.root, text="4. Proporção / Formato de Saída")
        f4.pack(fill="x", padx=10, pady=5)
        ttk.Combobox(f4, textvariable=self.aspect,
                     values=list(ASPECT_RATIOS.keys()),
                     state="readonly").pack(fill="x", **pad)
        ttk.Label(f4, text="↳ Vídeos com proporção diferente ganham fundo borrado bonito (não distorce).",
                  foreground="#555").pack(anchor="w", padx=10, pady=(0, 6))

        # ---- 5. Música ----
        f5 = ttk.LabelFrame(self.root, text="5. Música(s) de Fundo (opcional)")
        f5.pack(fill="x", padx=10, pady=5)

        row5a = ttk.Frame(f5); row5a.pack(fill="x", **pad)
        ttk.Checkbutton(row5a, text="Adicionar música(s) de fundo",
                        variable=self.use_music).pack(side="left")

        # Lista de músicas + barra de rolagem
        row5b = ttk.Frame(f5); row5b.pack(fill="x", **pad)
        list_frame = ttk.Frame(row5b)
        list_frame.pack(side="left", fill="x", expand=True, padx=(0, 6))
        sb = ttk.Scrollbar(list_frame, orient="vertical")
        self.music_listbox = Listbox(list_frame, height=4, selectmode=SINGLE,
                                     yscrollcommand=sb.set, activestyle="dotbox")
        sb.config(command=self.music_listbox.yview)
        sb.pack(side="right", fill="y")
        self.music_listbox.pack(side="left", fill="x", expand=True)

        btns = ttk.Frame(row5b); btns.pack(side="right", fill="y")
        ttk.Button(btns, text="Adicionar...", width=14,
                   command=self._add_music).pack(fill="x", pady=1)
        ttk.Button(btns, text="Remover", width=14,
                   command=self._remove_music).pack(fill="x", pady=1)
        ttk.Button(btns, text="Limpar tudo", width=14,
                   command=self._clear_music).pack(fill="x", pady=1)

        row5c = ttk.Frame(f5); row5c.pack(fill="x", **pad)
        ttk.Label(row5c, text="Volume da música:").pack(side="left")
        scale = ttk.Scale(row5c, from_=5, to=50, variable=self.music_volume,
                          orient="horizontal", command=self._update_vol_label)
        scale.pack(side="left", fill="x", expand=True, padx=8)
        self.vol_label = ttk.Label(row5c, text="20%", width=5)
        self.vol_label.pack(side="left")

        ttk.Label(f5,
                  text="↳ A música abaixa AUTOMATICAMENTE quando há voz no vídeo "
                       "(sidechain ducking) e volta quando não há.\n"
                  "↳ Com VÁRIAS músicas: cada corte recebe uma em rotação "
                  "(música 1→corte 1, 2→corte 2…); ao acabar a lista, volta para a 1ª.",
                  foreground="#555", wraplength=760, justify="left"
                  ).pack(anchor="w", padx=10, pady=(0, 6))

        # ---- Botões ----
        f6 = ttk.Frame(self.root); f6.pack(fill="x", padx=10, pady=8)
        self.btn_run = ttk.Button(f6, text="🎬  Processar Vídeo", command=self._run)
        self.btn_run.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(f6, text="⏹  Parar", command=self._stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        ttk.Button(f6, text="Limpar Log",
                   command=lambda: self.log_box.delete("1.0", "end")).pack(side="left", padx=4)

        # ---- Log ----
        f7 = ttk.LabelFrame(self.root, text="Log de Processamento")
        f7.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_box = ScrolledText(f7, height=10, wrap="word",
                                    font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)

        # ---- Progresso ----
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 10))

    def _update_vol_label(self, *args):
        self.vol_label.config(text=f"{int(self.music_volume.get())}%")

    def log(self, msg):
        """Thread-safe append no log."""
        def _append():
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
        self.root.after(0, _append)

    def _check_ffmpeg(self):
        self.ffmpeg, self.ffprobe = find_ffmpeg()
        if not self.ffmpeg or not self.ffprobe:
            self.log("⚠️  FFmpeg/ffprobe NÃO ENCONTRADOS no sistema.")
            self.log("    Instale o FFmpeg antes de processar (veja README.md).")
            messagebox.showwarning(
                "FFmpeg não encontrado",
                "O FFmpeg não foi encontrado no seu sistema.\n\n"
                "Instale-o e adicione ao PATH para usar este programa.\n"
                "Consulte o arquivo README.md para o passo a passo."
            )
        else:
            self.log(f"✔ ffmpeg:  {self.ffmpeg}")
            self.log(f"✔ ffprobe: {self.ffprobe}")
            self.log("Pronto para processar.\n")

    def _pick_video(self):
        p = filedialog.askopenfilename(title="Escolha o vídeo",
                                       filetypes=VIDEO_EXTENSIONS)
        if p:
            self.video_path.set(p)
            if not self.output_dir.get():
                self.output_dir.set(str(Path(p).parent / "cortes"))

    def _pick_output(self):
        p = filedialog.askdirectory(title="Escolha a pasta de saída")
        if p:
            self.output_dir.set(p)

    def _add_music(self):
        # askopenfilenames (com 's') permite seleção múltipla nativa
        paths = filedialog.askopenfilenames(
            title="Escolha uma ou mais músicas",
            filetypes=AUDIO_EXTENSIONS,
        )
        added = 0
        for p in paths:
            if not p or not os.path.exists(p):
                continue
            # Evita duplicar a mesma música
            if p in self.music_files:
                continue
            self.music_files.append(p)
            self.music_listbox.insert(END, Path(p).name)
            added += 1
        if added > 0:
            self.use_music.set(True)

    def _remove_music(self):
        sel = self.music_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.music_listbox.delete(idx)
        del self.music_files[idx]
        if not self.music_files:
            self.use_music.set(False)

    def _clear_music(self):
        self.music_listbox.delete(0, END)
        self.music_files.clear()
        self.use_music.set(False)

    def _stop(self):
        if not self.is_running:
            return
        self.log("\n⏹  Cancelamento solicitado pelo usuário...")
        self.btn_stop.config(state="disabled")
        # Dispara o cancelamento numa thread separada para não congelar
        # a UI enquanto o ffmpeg termina/é morto.
        threading.Thread(target=self.cancel_token.cancel, daemon=True).start()

    def _on_close(self):
        if self.is_running:
            if not messagebox.askyesno(
                "Sair?",
                "Há um processamento em andamento. Deseja interromper e sair?"
            ):
                return
            self.cancel_token.cancel()
        self.root.destroy()

    def _set_running(self, running):
        """Atualiza estado dos botões conforme está processando ou não."""
        self.is_running = running
        if running:
            self.btn_run.config(state="disabled")
            self.btn_stop.config(state="normal")
        else:
            self.btn_run.config(state="normal")
            self.btn_stop.config(state="disabled")

    def _validate(self):
        if not self.ffmpeg:
            messagebox.showerror("Erro", "FFmpeg não encontrado. Instale-o primeiro.")
            return False
        v = self.video_path.get().strip()
        if not v or not os.path.exists(v):
            messagebox.showerror("Erro", "Selecione um vídeo válido.")
            return False
        o = self.output_dir.get().strip()
        if not o:
            messagebox.showerror("Erro", "Selecione uma pasta de saída.")
            return False
        if self.use_music.get():
            if not self.music_files:
                messagebox.showerror("Erro",
                                     "A opção 'Adicionar música(s) de fundo' está marcada, "
                                     "mas a lista está vazia. Adicione ao menos uma "
                                     "música ou desmarque a opção.")
                return False
            # Verifica se todas ainda existem
            missing = [p for p in self.music_files if not os.path.exists(p)]
            if missing:
                messagebox.showerror(
                    "Erro",
                    "As seguintes músicas não foram encontradas:\n\n"
                    + "\n".join(Path(p).name for p in missing)
                )
                return False
        if self.mode.get() == "duration":
            try:
                d = float(self.duration_value.get().replace(",", "."))
                if d <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Erro", "Duração inválida. Use um número > 0.")
                return False
        else:
            try:
                n = int(self.parts_value.get())
                if n < 1:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Erro", "Número de partes inválido. Use inteiro >= 1.")
                return False
        return True

    def _run(self):
        if not self._validate():
            return
        self.cancel_token.reset()
        self._set_running(True)
        threading.Thread(target=self._do_work, daemon=True).start()

    def _do_work(self):
        try:
            video = self.video_path.get().strip()
            outdir = self.output_dir.get().strip()
            os.makedirs(outdir, exist_ok=True)

            self.log(f"\n📹 Analisando: {Path(video).name}")
            duration, w, h, has_audio = get_video_info(video, self.ffprobe)
            self.log(f"   Duração: {duration:.2f}s ({duration/60:.2f} min)")
            self.log(f"   Resolução original: {w}x{h}")
            self.log(f"   Áudio original: {'sim' if has_audio else 'NÃO (vídeo silencioso)'}")

            if self.mode.get() == "duration":
                d = float(self.duration_value.get().replace(",", "."))
                segments = calc_segments_by_duration(duration, d)
                self.log(f"\n   Modo: cortes de {d}s")
            else:
                n = int(self.parts_value.get())
                segments = calc_segments_by_parts(duration, n)
                self.log(f"\n   Modo: dividir em {n} partes iguais")

            if not segments:
                self.log("❌ Nenhum corte calculado. Verifique os parâmetros.")
                return

            self.log(f"   Total de cortes: {len(segments)}")
            for i, s in enumerate(segments, 1):
                self.log(f"      Parte {i}: {s:.2f}s ({s/60:.2f} min)")
            self.log(f"   Soma total: {sum(segments):.2f}s "
                     f"(original: {duration:.2f}s)")

            # Snapshot das músicas e info de rotação
            use_music = self.use_music.get()
            music_list = list(self.music_files) if use_music else []
            if music_list:
                if len(music_list) == 1:
                    self.log(f"\n   🎵 Música: {Path(music_list[0]).name} "
                             f"(em todos os cortes)")
                else:
                    self.log(f"\n   🎵 {len(music_list)} músicas em rotação:")
                    for i, m in enumerate(music_list, 1):
                        self.log(f"      {i}. {Path(m).name}")
                    if len(segments) > len(music_list):
                        self.log(f"   ↳ Como há {len(segments)} cortes e "
                                 f"{len(music_list)} músicas, a lista vai se "
                                 f"repetir (música 1 volta após a {len(music_list)}ª).")
            self.log("")

            base_name = sanitize_filename(Path(video).stem)
            self.progress.config(maximum=len(segments), value=0)

            current = 0.0
            success = 0
            cancelled = False
            vol = self.music_volume.get() / 100.0

            for i, seg_dur in enumerate(segments, 1):
                # Verificação ANTES de iniciar o próximo corte
                if self.cancel_token.is_cancelled():
                    cancelled = True
                    break

                out_file = Path(outdir) / f"{base_name}_Parte{i}.mp4"

                # Rotação cíclica das músicas: música[(i-1) % N]
                # i=1 → music[0], i=2 → music[1], ..., i=N+1 → music[0] de novo
                if music_list:
                    music = music_list[(i - 1) % len(music_list)]
                    self.log(f"   🎵 Parte {i} usa: {Path(music).name}")
                else:
                    music = ""

                ok = process_segment(
                    self.ffmpeg, video, current, seg_dur, out_file,
                    self.aspect.get(), music, vol, has_audio, self.log,
                    token=self.cancel_token,
                )

                # Após o ffmpeg retornar, verifica novamente se foi cancelado
                if self.cancel_token.is_cancelled():
                    cancelled = True
                    break

                if ok:
                    success += 1

                current += seg_dur
                self.root.after(0, lambda v=i: self.progress.config(value=v))

            self.log(f"\n{'='*60}")
            if cancelled:
                self.log(f"⏹  INTERROMPIDO: {success}/{len(segments)} cortes "
                         f"finalizados antes do cancelamento")
            else:
                self.log(f"✅ CONCLUÍDO: {success}/{len(segments)} cortes gerados")
            self.log(f"   Pasta: {outdir}")
            self.log(f"{'='*60}\n")

            if cancelled:
                messagebox.showinfo(
                    "Cancelado",
                    f"Operação interrompida.\n"
                    f"{success} corte(s) já gerados estão em:\n{outdir}"
                )
            elif success == len(segments):
                messagebox.showinfo(
                    "Sucesso",
                    f"{success} cortes gerados com sucesso em:\n{outdir}"
                )
            else:
                messagebox.showwarning(
                    "Parcial",
                    f"{success} de {len(segments)} cortes finalizados. "
                    "Verifique o log para detalhes dos erros."
                )

        except Exception as e:
            self.log(f"\n❌ ERRO INESPERADO: {e}")
            messagebox.showerror("Erro", str(e))
        finally:
            self.root.after(0, lambda: self._set_running(False))


def main():
    root = Tk()
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

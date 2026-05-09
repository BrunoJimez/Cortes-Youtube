# 🎬 Cortador de Vídeos - TikTok / Instagram

Sistema em Python para cortar vídeos automaticamente em segmentos, ajustar a
proporção (9:16, 16:9, 1:1, 4:5) e adicionar música de fundo com mixagem
profissional (sidechain ducking).

---

## 📋 O que ele faz

✅ Corta vídeos em **duração fixa** (ex: cada corte de 60s) **ou** em **N partes
   iguais** (ex: dividir em 7 partes), com a soma exata garantida pela
   matemática descrita.

✅ Ajusta a **proporção** automaticamente para 9:16 (TikTok/Reels/Shorts), 16:9,
   1:1, 4:5 ou mantém a original. Vídeos com proporção diferente recebem um
   **fundo borrado** lindo nas bordas (não distorce, não corta a imagem).

✅ Mixa **música de fundo** com *sidechain ducking*: a música abaixa
   automaticamente quando há voz/áudio principal, e volta quando não há. Isso
   garante que a voz **nunca** fica abafada e a música **nunca** fica baixa
   demais — é o mesmo princípio usado em rádio e podcasts profissionais.

✅ Aceita **qualquer formato** suportado pelo FFmpeg: mp4, mov, avi, mkv,
   webm, flv, wmv, m4v, mpg, ts, 3gp, etc.

✅ Saída em **H.264 + AAC + yuv420p**, exatamente o que TikTok e Instagram
   recomendam (não vai precisar reconverter quando subir).

✅ Nomeia os arquivos como `NomeOriginal_Parte1.mp4`, `_Parte2.mp4`...

---

## 🛠️ Instalação - Passo a Passo

Você precisa de **2 coisas**: Python (linguagem) e FFmpeg (motor de vídeo).

### 🪟 No Windows

#### 1. Instale o Python 3.10+

1. Vá em https://www.python.org/downloads/
2. Baixe a versão mais recente para Windows
3. **IMPORTANTE**: na primeira tela do instalador, marque a caixa
   **"Add Python to PATH"** antes de clicar em "Install Now"
4. Termine a instalação

Confirme abrindo o **Prompt de Comando** (cmd) e digitando:
```
python --version
```
Deve mostrar algo como `Python 3.12.x`.

#### 2. Instale o FFmpeg

**Maneira mais fácil (recomendada)** — via `winget` (já vem no Windows 10/11):

Abra o **PowerShell como Administrador** e digite:
```powershell
winget install --id Gyan.FFmpeg
```

**Feche e reabra o Prompt de Comando** depois disso, então confirme:
```
ffmpeg -version
```

> **Alternativa manual**: baixe o FFmpeg em https://www.gyan.dev/ffmpeg/builds/
> (escolha "release essentials"), extraia em `C:\ffmpeg`, e adicione
> `C:\ffmpeg\bin` ao PATH do Windows. (Se preferir esse caminho, pesquise
> "como adicionar pasta ao PATH no Windows".)

#### 3. Rode o programa

Abra o Prompt de Comando, navegue até a pasta onde você salvou
`cortador_video.py` e rode:
```
python cortador_video.py
```

A janela do programa abre.

---

### 🍎 No macOS

```bash
# 1. Instale o Homebrew (se ainda não tiver)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Instale Python e FFmpeg
brew install python ffmpeg

# 3. Confirme
python3 --version
ffmpeg -version

# 4. Rode o programa
python3 cortador_video.py
```

---

### 🐧 No Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3 python3-tk ffmpeg

# Confirme
python3 --version
ffmpeg -version

# Rode
python3 cortador_video.py
```

> No Linux, o pacote `python3-tk` é necessário para a interface gráfica.

---

## 🚀 Como Usar

1. **Execute o programa**: `python cortador_video.py` (ou `python3` no Mac/Linux).
2. Na janela:
   - **Vídeo de Entrada**: clique em "Selecionar..." e escolha seu vídeo.
   - **Pasta de Saída**: escolha onde os cortes serão salvos (o programa
     sugere uma pasta `cortes/` ao lado do vídeo).
   - **Modo de Corte**: marque uma das opções:
     - `Por DURAÇÃO`: digite, por exemplo, `60` (cortes de 60 segundos cada).
     - `Em N PARTES`: digite, por exemplo, `7` (divide em 7 partes iguais).
   - **Proporção**: escolha o formato de saída. Se for postar no TikTok, Reels
     ou Shorts, deixe **9:16**.
   - **Música de Fundo** (opcional): marque a caixa, selecione um arquivo
     de áudio e ajuste o volume (recomendado: **15-25%**).
3. Clique em **🎬 Processar Vídeo**.
4. Acompanhe pelo log. Ao final, abra a pasta de saída e seus cortes estarão
   prontos para subir.

---

## 💡 Dicas para TikTok / Instagram

| Plataforma                  | Proporção | Duração ideal por corte |
| --------------------------- | --------- | ----------------------- |
| TikTok                      | 9:16      | 21–60s (engaja melhor)  |
| Instagram Reels             | 9:16      | 15–60s                  |
| YouTube Shorts              | 9:16      | até 60s                 |
| Instagram Feed (vídeo)      | 1:1 ou 4:5| até 60s                 |
| Instagram Stories           | 9:16      | 15s por slide           |

**Volume da música**: 15–20% costuma ser ideal para vídeos com fala. Se for
um vídeo só visual (sem voz), pode subir para 30–40%.

---

## 🎚️ Como funciona o sidechain ducking (por dentro)

Quando você adiciona música, o programa faz isto no FFmpeg:

1. **Reduz** a música ao volume que você escolheu (ex: 20%).
2. **Duplica** o áudio principal (voz) em duas vias: uma vai pro mix final,
   a outra serve de "gatilho".
3. Aplica `sidechaincompress` na música usando a voz como gatilho:
   sempre que a voz toca acima de um limiar, a música é comprimida
   automaticamente. Quando a voz para, a música volta ao volume normal.
4. **Mixa** as duas vias.

Resultado: a voz sempre fica nítida, e a música preenche o silêncio sem
abafar nada. É o mesmo efeito que rádios e podcasts usam.

---

## ❓ Solução de problemas

**"FFmpeg não encontrado"** → você não instalou o FFmpeg, ou ele não está
no PATH. No Windows, feche e reabra o Prompt de Comando depois de instalar.

**"No module named 'tkinter'"** (Linux) → instale com
`sudo apt install python3-tk`.

**Erro no processamento** → veja o log na própria janela. A maior parte das
vezes é caractere especial no nome do arquivo, ou pasta sem permissão de
escrita.

**Vídeo de saída fica "esticado"** → você escolheu uma proporção diferente
da original. O programa NÃO estica: ele coloca um fundo borrado nas bordas.
Se quiser cortar a imagem em vez de adicionar bordas, escolha "Original".

**Música muito alta ou baixa** → ajuste o slider. O ducking compensa
automaticamente, mas se sua voz for muito baixa no original, suba para 30%.
Se sua voz for muito alta, abaixe para 10%.

---

## 📂 Estrutura

```
cortador_video/
├── cortador_video.py    ← o programa
└── README.md            ← este arquivo
```

Não há outras dependências além do Python padrão e do FFmpeg externo.

# Controle Remoto Samsung — App Android

Aplicativo Android (Kotlin + Jetpack Compose) que transforma o smartphone em um
**controle remoto completo** para Smart TVs Samsung conectadas à mesma rede Wi-Fi.
O app descobre TVs Samsung na LAN, faz o pareamento (handshake de token) e envia
comandos de controle — navegação, volume, canais, energia, entrada de texto e atalhos
dedicados para apps de streaming — falando o protocolo WebSocket do Samsung Tizen
(portas `8001`/`8002`).

Funciona com modelos modernos (4K, QLED, Crystal, Neo QLED e OLED, ~2016+) e opera
**100% na rede local**: sem nuvem, sem conta, sem telemetria.

---

## ✨ Funcionalidades

- **Descoberta automática** de TVs Samsung na LAN via SSDP (multicast UDP) e mDNS (NSD),
  com validação REST (`/api/v2/`) e **entrada manual de IP** quando o multicast é bloqueado.
- **Pareamento seguro:** a TV exibe o prompt de autorização; o token retornado é
  persistido **cifrado** (Android Keystore) e reusado nas próximas conexões.
- **Controle completo:** D-pad, OK/Return/Home/Menu, volume/mute, canais, teclado
  numérico, transporte de mídia (play/pause/stop/rew/ff) e entrada de texto.
- **Atalhos de apps de streaming:** Netflix, Prime Video, Disney+ e YouTube
  (com descoberta de apps instalados em runtime e fallback configurável).
- **Sessão resiliente:** uma única conexão WebSocket (`RemoteSession`) como fonte de
  verdade, com reconexão automática por backoff exponencial.
- **Wake-on-LAN:** liga a TV totalmente desligada via *magic packet* UDP para o MAC
  conhecido.
- **Reconciliação de IP (DHCP):** se o IP da TV muda, o app re-descobre pelo *device id*
  e reconecta sozinho.

---

## 🏗️ Arquitetura

Fluxo em camadas com baixo acoplamento — **UI → ViewModel → Repository → Transport** —
e app **single-activity** com navegação modelada por estado selado:

```
Screen.Discovery ──onTvSelected(tv)──▶ Screen.Pairing(tv) ──onPaired(token)──▶ Screen.Remote(tv, token)
```

Cada tela segue o padrão **Route (stateful) / Screen (stateless)**, mantendo a UI pura
testável em isolamento.

| Camada | Componentes principais |
|--------|------------------------|
| **UI (Compose)** | `MainActivity`, `DiscoveryScreen`, `PairingScreen`, `RemoteScreen` (Material 3) |
| **ViewModels** | `DiscoveryViewModel`, `PairingViewModel`, `RemoteViewModel` (`StateFlow`) |
| **Descoberta** | `DiscoveryService`, `SsdpCandidateSource`, `MdnsCandidateSource`, `RestTvCandidateValidator`, `TvReconciler` |
| **Pareamento** | `PairingManager`, `LanTrustManager` (TLS auto-assinado só na LAN) |
| **Sessão / Transporte** | `RemoteSession`, `CommandTransport`, `ConnectionState` (OkHttp WebSocket) |
| **Protocolo** | `TizenProtocol`, `TizenMessage` (único ponto que conhece o formato de fio) |
| **Domínio** | `CommandRepository`, `RemoteKeyCatalog`, `AppShortcutCatalog` |
| **Persistência** | `TvRegistry` (Room) + `KeystoreTokenCipher` (Android Keystore) |
| **Wake-on-LAN** | `WakeOnLan` (magic packet UDP) |
| **DI** | Hilt (`AppModule`, `DiscoveryModule`, `PairingModule`, `SessionModule`) |

> Documentação detalhada em [`docs/architecture.md`](docs/architecture.md),
> decisões em [`docs/decisions.md`](docs/decisions.md) e operação em
> [`docs/operations.md`](docs/operations.md).

---

## 🧰 Stack

- **Kotlin** + **Jetpack Compose** (Material 3) — `minSdk` 26 (Android 8.0), `targetSdk` 35
- **Hilt** (injeção de dependências) · **KSP**
- **OkHttp** (HTTP + WebSocket) · **Room** (persistência) · **Jetpack Security / Tink** (cifra)
- **Coroutines / Flow**
- Build: **Gradle** (wrapper versionado) · JDK **17**

---

## 🚀 Como compilar e rodar

### Pré-requisitos

- **JDK 17** no `PATH`
- **Android SDK** + `adb` no `PATH`
- (opcional) **GNU Make** para os atalhos do `Makefile`
- (opcional) **Python 3.12** + `pytest` para a suíte de testes da fábrica em `tests/`

O caminho do SDK fica em `local.properties` (não versionado). Crie o arquivo na raiz
do projeto com:

```properties
sdk.dir=C\:\\Users\\<voce>\\AppData\\Local\\Android\\Sdk
```

> **Alternativa sem `local.properties`:** em vez de criar o arquivo, você pode definir a
> variável de ambiente **`ANDROID_HOME`** (ou `ANDROID_SDK_ROOT`) apontando para o SDK —
> o Android Gradle Plugin a usa quando não encontra o `local.properties`. Ex.:
> - **Windows (PowerShell):** `setx ANDROID_HOME "C:\Users\<voce>\AppData\Local\Android\Sdk"`
> - **Linux/macOS:** `export ANDROID_HOME="$HOME/Android/Sdk"`

### Comandos (Makefile)

`make help` lista todos os alvos. Os mais usados:

| Comando | O que faz |
|---------|-----------|
| `make doctor` | Checa Java, `adb` e dispositivos conectados |
| `make build` | Compila e roda as verificações do módulo `app` |
| `make assemble-debug` | Gera o APK debug |
| `make install-debug` | Pré-checa o device e instala o APK no aparelho conectado |
| `make test` | Testes unitários JVM |
| `make android-test` | Testes instrumentados (Room + Compose UI) em device conectado |
| `make lint` | Lint Android |
| `make app-start` / `make adb-logcat` | Abre o app / mostra logs em tempo real |

> No Windows o `Makefile` chama `./gradlew.bat`. Sem Make, use os alvos Gradle
> diretamente, ex.: `./gradlew.bat :app:installDebug`.

### Instalando em um celular físico

1. Em *Configurações → Sobre o telefone*, toque **7×** em **Número da versão** para
   habilitar as *Opções do desenvolvedor*.
2. Ative a **Depuração USB**, conecte por um cabo de **dados** e **autorize** o prompt RSA.
3. Confirme com `make doctor` (o aparelho deve aparecer com status `device`).
4. `make install-debug` e depois `make app-start`.

Passo a passo completo (incluindo depuração sem fio) em
[`docs/operations.md`](docs/operations.md) §6.

---

## 📱 Como usar

1. **Conecte o telefone à mesma rede Wi-Fi da TV.**
2. **Descoberta** — a tela inicial lista as TVs encontradas; se a rede bloqueia
   multicast, use a entrada manual de IP.
3. **Pareamento** — selecione a TV e **aceite o prompt exibido na própria TV**. O token
   é salvo cifrado e reusado depois.
4. **Controle** — use o D-pad, volume, canais, mídia, teclado, texto e os atalhos de apps.
5. **Ligar a TV** — o botão Power usa Wake-on-LAN quando a TV está desligada (requer MAC
   conhecido, capturado na descoberta/pareamento).

---

## 🧪 Testes

Duas suítes complementares:

1. **pytest (`tests/`)** — runner de CI da fábrica. Rode `pytest` na raiz. Quando há
   toolchain Kotlin nas caches do Gradle, vários testes compilam e executam o código
   Kotlin real; caso contrário fazem checagem estrutural e dão `skip`. O contrato de fio
   do protocolo é o golden `tests/contracts/tizen_protocol_v2.json`.
2. **Testes nativos Android** — `make test` (unitários JVM, transporte mockado via
   `CommandTransport`) e `make android-test` (instrumentados: `KnownTvDaoTest`, Compose
   UI com `RemoteTestTags`, acessibilidade/TalkBack).

Build/inicialização end-to-end: `tests/test_app_build_and_launch_e2e.py`
(rode os testes lentos com `pytest -m slow`).

---

## 🔌 Protocolo Tizen (resumo)

Toda a serialização/parse fica isolada em `TizenProtocol`:

| Ação de domínio | Tipo Tizen | Transporte |
|-----------------|-----------|-----------|
| `sendKey("KEY_VOLUP")` | `SendRemoteKey` (`ms.remote.control`) | WebSocket |
| `launchApp("11101200001")` | `ed.apps.launch` | REST `POST /api/v2/applications/{appId}` (fallback WebSocket) |
| `sendText("hi")` | `SendInputString` (Base64) | REST `imeInput` (best-effort, fallback WebSocket) |

Detalhes e tabela completa em [`docs/architecture.md`](docs/architecture.md) §9.

---

## 🔐 Permissões

Apenas rede — nenhuma sensível:

- `INTERNET`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE` — sockets e estado da rede.
- `CHANGE_WIFI_MULTICAST_STATE` — necessária para SSDP/mDNS (multicast UDP).

Sem localização, armazenamento ou telemetria — coerente com a operação 100% LAN.

---

## 📁 Estrutura do projeto

```
app/
  src/main/java/com/factory/samsungremote/
    MainActivity.kt          # host Compose (Discovery → Pairing → Remote)
    ui/                      # discovery / pairing / remote / theme (Compose, Material 3)
    viewmodel/               # Discovery / Pairing / Remote ViewModels
    data/                    # repository, registry, db (Room), crypto (Keystore)
    network/                 # discovery, pairing, session, protocol, wol
    di/                      # módulos Hilt
docs/                        # architecture · decisions · operations
tests/                       # suíte pytest da fábrica + contracts/ (golden)
Makefile                     # atalhos Gradle/adb (make help)
```

---

## 📄 Licença

Projeto privado. Uso interno.

# Arquitetura — Controle Remoto Android para Samsung Smart TV

## 1. Visão

Aplicativo Android que transforma o smartphone em um controle remoto completo para
Smart TVs Samsung conectadas à mesma rede Wi-Fi. O app descobre TVs Samsung na rede
local, realiza o pareamento (handshake de token), e envia comandos de controle —
navegação, volume, canais, energia, entrada de texto e teclas de atalho dedicadas
para apps (Netflix, Prime Video, Disney+, YouTube). Funciona com modelos modernos
(4K, QLED, Crystal, Neo QLED e OLED) que expõem a API WebSocket do Samsung Tizen
(`samsungtvws` / porta 8001/8002).

O foco é uma experiência de controle responsiva (latência baixa entre toque e ação na
TV), confiável (reconexão automática) e fiel a um controle físico, incluiindo teclas
de atalho para serviços de streaming.

## 2. Princípios arquiteturais

1. **Single source of truth de conexão.** Um único `RemoteSession` mantém o estado do
   WebSocket; toda a UI observa esse estado, nunca abre sockets paralelos.
2. **Comandos como dados.** Cada ação do controle é um objeto `RemoteKey` imutável,
   desacoplando a UI do protocolo de transporte.
3. **Baixo acoplamento por camadas.** UI → ViewModel → Repository → Transport. Cada
   camada é testável isoladamente e substituível (ex.: trocar transporte WebSocket por
   um mock em testes).
4. **Resiliência primeiro.** Descoberta, pareamento e envio toleram falhas de rede com
   retry/backoff e reconexão automática; o usuário nunca fica preso em estado inválido.
5. **YAGNI.** Sem multiusuário, sem nuvem, sem conta. Tudo roda no device e na LAN.
6. **Segurança do token.** O token de pareamento é persistido cifrado e nunca sai do
   aparelho.

## 3. Componentes

| Componente | Responsabilidade | Stack |
|------------|------------------|-------|
| **Navigation host (`MainActivity`)** | Single-activity que hospeda o fluxo Discovery → Pairing → Remote; o destino atual é modelado por uma `sealed interface Screen` que carrega a TV selecionada e o token de pareamento para a próxima tela (ver §14) | Kotlin, Jetpack Compose, navigation-compose |
| **UI (Compose)** | Pares `*Route` (stateful, observam ViewModel/`StateFlow`) → `*Screen` (stateless, recebem estado + callbacks): `DiscoveryRoute/Screen`, `PairingRoute/Screen`, `RemoteRoute/Screen` (D-pad, volume, canais, teclado numérico, media transport, entrada de texto, atalhos de apps) | Kotlin, Jetpack Compose, Material 3 |
| **ViewModels** | `DiscoveryViewModel`, `PairingViewModel`, `RemoteViewModel`: estado de tela, mapeiam toques → `RemoteIntent`, expõem `StateFlow` | Kotlin, AndroidX ViewModel, Coroutines/Flow |
| **DiscoveryService** | Orquestra a descoberta combinando fontes de candidatos e validação | Kotlin, Coroutines |
| **TvCandidateSource (SSDP/mDNS)** | `SsdpCandidateSource` (multicast UDP) e `MdnsCandidateSource` (NSD) produzem candidatos de TV na LAN | Kotlin, UDP multicast, Android NSD |
| **RestTvCandidateValidator** | Confirma que um candidato é uma TV Samsung consultando `/api/v2/` e extrai device info (`SamsungDeviceInfoParser`) | OkHttp |
| **TvReconciler** | Reconcilia o IP persistido com o IP atual (DHCP mudou) por device id e reconecta a sessão | Kotlin, Coroutines |
| **PairingManager** | Handshake e obtenção do token de autorização; modela falhas via `PairingFailureReason`/`PairingException` | OkHttp WebSocket |
| **LanTrustManager** | Aceita o certificado TLS auto-assinado da TV apenas para a sessão LAN (porta 8002) | javax.net.ssl |
| **RemoteSession** | Conexão WebSocket persistente; envia frames, recebe eventos; reconexão com backoff; expõe `ConnectionState` | OkHttp WebSocket, Coroutines |
| **CommandTransport** | Seam de envio de frames (interface) que isola `CommandRepository` da sessão real; mockável em testes | Kotlin |
| **TizenProtocol / TizenMessage** | Único ponto que conhece o formato de fio: serializa `sendKey`/`sendText`/`launchApp` e faz parse de eventos/token | Kotlin, org.json |
| **CommandRepository** | API de domínio (`sendKey`, `sendText`, `launchApp`); retorna se o frame alcançou conexão aberta | Kotlin |
| **RemoteKeyCatalog / AppShortcutCatalog** | Catálogos estáticos imutáveis de teclas (`KEY_*`) e apps de streaming (IDs Tizen) | Kotlin |
| **WakeOnLan** | Liga TV totalmente desligada via "magic packet" UDP para o MAC persistido | Kotlin, UDP broadcast |
| **TvRegistry** | Persiste TVs conhecidas e seus tokens (cifrados) | Room + `KeystoreTokenCipher` (Android Keystore) |
| **DI (Hilt)** | Módulos `AppModule`, `DiscoveryModule`, `PairingModule`, `SessionModule` provêm dependências e clients OkHttp dedicados | Hilt |

## 4. Modelo de dados

Persistência local (Room). Entidades principais:

**KnownTv**
| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | String (PK) | UUID/device id da TV |
| `name` | String | Nome amigável (modelo) |
| `ipAddress` | String | Último IP conhecido na LAN |
| `macAddress` | String? | Usado para Wake-on-LAN (ligar TV) |
| `tokenEncrypted` | String? | Token de pareamento cifrado |
| `lastConnectedAt` | Long | Timestamp |

**RemoteKey** (em memória / catálogo estático, não persistido)
| Campo | Tipo | Notas |
|-------|------|-------|
| `code` | String | Ex.: `KEY_VOLUP`, `KEY_ENTER`, `KEY_HOME` |
| `category` | Enum | NAV, MEDIA, VOLUME, POWER, NUMERIC, SHORTCUT |
| `label` | String | Rótulo exibido |

**AppShortcut** (catálogo estático)
| Campo | Tipo | Notas |
|-------|------|-------|
| `appId` | String | ID Tizen do app (ex.: Netflix `11101200001`) |
| `name` | String | Netflix, Prime Video, Disney+, YouTube |
| `deepLinkKey` | String? | Tecla/atalho alternativo |

Relações: `KnownTv` 1—N sessões (efêmeras). `RemoteKey` e `AppShortcut` são catálogos
estáticos referenciados pelos comandos.

## 5. Fluxo end-to-end

**Cenário: usuário abre o Netflix na TV pelo botão de atalho.**

1. App inicia → `DiscoveryService` faz multicast SSDP → encontra a Samsung TV no IP
   `192.168.0.42`.
2. Usuário seleciona a TV. `TvRegistry` não tem token → `PairingManager` abre WebSocket
   em `wss://192.168.0.42:8002/...?name=<base64>`; a TV exibe prompt de autorização.
3. Usuário aceita na TV → WebSocket retorna `data.token` → `TvRegistry` salva
   `tokenEncrypted`.
4. `RemoteSession` mantém o socket aberto. UI de controle é exibida.
5. Usuário toca no atalho **Netflix** → ViewModel emite intent → `CommandRepository`
   chama `launchApp("11101200001")` → mensagem JSON enviada pelo `RemoteSession`.
6. TV abre o Netflix. Eventos de status retornam pelo socket e atualizam o `StateFlow`
   observado pela UI.

## 6. Estrutura de diretórios

```
app/
  src/main/java/com/factory/samsungremote/
    MainActivity.kt              # host Compose; sealed Screen (Discovery→Pairing→Remote)
    SamsungRemoteApp.kt          # Application com @HiltAndroidApp
    ui/
      discovery/DiscoveryScreen.kt   # DiscoveryRoute (stateful) + DiscoveryScreen; entrada manual de IP
      pairing/PairingScreen.kt       # PairingRoute (stateful) + PairingScreen; pareamento (prompt na TV)
      remote/RemoteScreen.kt         # RemoteRoute (stateful) + RemoteScreen; controle (RemoteTestTags p/ UI tests)
      theme/                         # Color, Theme, Type (Material 3)
    viewmodel/
      DiscoveryViewModel.kt
      PairingViewModel.kt
      RemoteViewModel.kt             # RemoteIntent: PressKey/TypeText/LaunchApp
    data/
      repository/CommandRepository.kt
      registry/
        TvRegistry.kt                # TVs conhecidas + tokens
        RemoteKey.kt, RemoteKeyCatalog.kt      # catálogo de teclas KEY_*
        AppShortcut.kt, AppShortcutCatalog.kt  # catálogo de apps de streaming
      db/                            # Room: KnownTv, KnownTvDao, AppDatabase, AppDatabaseMigrations
      crypto/                        # TokenCipher + KeystoreTokenCipher (Android Keystore)
    network/
      discovery/
        DiscoveryService.kt          # orquestra fontes + validação
        SsdpCandidateSource.kt, MdnsCandidateSource.kt, TvCandidateSource.kt
        RestTvCandidateValidator.kt, TvCandidateValidator.kt, SamsungDeviceInfoParser.kt
        DiscoveredTv.kt, TvReconciler.kt
      pairing/
        PairingManager.kt, PairingException.kt, LanTrustManager.kt
      session/
        RemoteSession.kt, CommandTransport.kt, ConnectionState.kt
      protocol/
        TizenProtocol.kt, TizenMessage.kt   # formato de fio isolado
      wol/WakeOnLan.kt               # Wake-on-LAN (magic packet)
    di/                              # AppModule, DiscoveryModule, PairingModule, SessionModule
  src/main/AndroidManifest.xml       # permissões de rede LAN
  src/test/                          # testes unitários JVM (transporte mockado)
  src/androidTest/                   # testes instrumentados (Room + Compose UI)
tests/                               # testes pytest (convenção da fábrica) + contracts/
  contracts/tizen_protocol_v2.json   # contrato de fio versionado (golden)
docs/
  architecture.md
  decisions.md
  operations.md                      # guia de build, testes e operação
Makefile                             # atalhos Gradle/adb (make help)
build.gradle.kts
```

## 7. Requisitos não-funcionais

- **Latência:** toque → comando na TV < 150 ms na mesma LAN.
- **Conectividade:** reconexão automática em < 3 s após queda de Wi-Fi; descoberta
  completa < 5 s.
- **Compatibilidade:** Android 8.0 (API 26)+; TVs Samsung Tizen com WebSocket
  (linhas 4K, QLED, Crystal, Neo QLED, OLED, ~2016+).
- **Segurança:** token cifrado em repouso; comunicação apenas na LAN; nenhuma
  telemetria externa.
- **Custo:** zero custo de backend (app 100% local/LAN).
- **Acessibilidade:** alvos de toque ≥ 48 dp; suporte a TalkBack nos botões.

## 8. Riscos conhecidos

| Risco | Impacto | Mitigação |
|-------|---------|-----------|
| TVs mais novas usam TLS auto-assinado na porta 8002 | Falha de handshake | Trust manager dedicado que aceita o cert da TV apenas para a sessão LAN |
| IP da TV muda (DHCP) | Conexão quebra | Reconciliação por device id + redescoberta SSDP/mDNS |
| Variação de IDs de apps Tizen entre modelos | Atalho não abre o app | Catálogo configurável + fallback para navegação por tecla |
| Multicast SSDP bloqueado em algumas redes | Descoberta falha | Fallback para mDNS e entrada manual de IP |
| Mudanças no protocolo Samsung não documentado | Quebra futura | Camada `protocol/` isolada e versionada; testes de contrato |
| Ligar TV desligada (socket indisponível) | Botão power não liga | Wake-on-LAN via MAC persistido |

## 9. Protocolo Tizen (formato de fio implementado)

Toda a serialização/parse vive isolada em `TizenProtocol` (ADR-0003). O contrato é
fixado em `tests/contracts/tizen_protocol_v2.json` (golden, versionado): qualquer
mudança no formato quebra os testes de contrato de propósito e exige um novo arquivo
(`tizen_protocol_v3.json`), nunca a edição dos snapshots.

| Ação de domínio | Método / tipo Tizen | JSON enviado (exemplo) |
|-----------------|---------------------|------------------------|
| `sendKey("KEY_VOLUP")` | `ms.remote.control` / `SendRemoteKey` | `{"method":"ms.remote.control","params":{"Cmd":"Click","DataOfCmd":"KEY_VOLUP","Option":"false","TypeOfRemote":"SendRemoteKey"}}` |
| `launchApp("11101200001")` | `ms.channel.emit` / `ed.apps.launch` | `{"method":"ms.channel.emit","params":{"event":"ed.apps.launch","to":"host","data":{"action_type":"DEEP_LINK","appId":"11101200001"}}}` |
| `sendText("hi")` | `ms.remote.control` / `SendInputString` | `{"method":"ms.remote.control","params":{"Cmd":"aGk=","DataOfCmd":"base64","TypeOfRemote":"SendInputString"}}` (texto em Base64) |

- `sendKey` aceita `CLICK` (padrão), `PRESS` e `RELEASE` (long-press).
- `launchApp` aceita `DEEP_LINK` (padrão) e `NATIVE_LAUNCH`.
- **Plano de controle REST (ADR-0010).** Em firmware Tizen 2020+ o WebSocket de
  controle honra `SendRemoteKey`, mas ignora `ed.apps.launch` e `SendInputString`.
  Por isso `RemoteSession` roteia launch e texto pelo REST em `http://<ip>:8001/api/v2/`
  (OkHttp inline, reaproveitando o client LAN da descoberta), caindo de volta para o
  frame WebSocket se o REST falhar:
  `launchApp` → `POST /api/v2/applications/{appId}`; `sendText` →
  `POST /api/v2/remoteControl/imeInput/{base64}?token={token}` (best-effort).
- `parseEvent`/`parseToken` extraem `event` e `data.token` da resposta da TV
  (retornam `null` para token ausente/nulo/vazio ou JSON inválido).
- As chaves do JSON são emitidas em ordem de inserção determinística para manter a
  saída estável e testável.

## 10. Conexão e ciclo de vida (`ConnectionState`)

`RemoteSession` é a única fonte de verdade de conectividade; a UI observa o
`StateFlow<ConnectionState>` e nunca chega a um beco sem saída — uma queda passa por
`Reconnecting(n)` (backoff exponencial) e volta a `Connected`; só o esgotamento do
orçamento de tentativas vira `Error` terminal.

```
Disconnected ──connect()──▶ Connecting ──socket open──▶ Connected
                                 │                          │
                                 │ falha                drop/close
                                 ▼                          ▼
                           Reconnecting(n) ◀──── backoff ───┘
                                 │
                      tentativas esgotadas ──▶ Error
                                 │
                         disconnect() ──▶ Disconnected
```

**Power quando a TV está desligada.** Se um `PressKey(KEY_POWER)` não alcança uma
conexão aberta, o `RemoteViewModel` dispara um Wake-on-LAN (magic packet UDP: 6 bytes
`0xFF` + MAC repetido 16× = 102 bytes) para o `macAddress` persistido da TV. Se o MAC
é desconhecido, o WoL é simplesmente ignorado (sem crash no caminho de controle).

**Mudança de IP (DHCP).** `TvReconciler.reconcileAndReconnect` re-descobre a TV pelo
device id; se o IP mudou, aplica `TvRegistry.updateIp` e reconecta — caso contrário
retorna `NotFound` (TV provavelmente desligada), sem lançar exceção.

## 11. Catálogo de teclas e atalhos (cobertura de "controle completo")

Definidos em `RemoteKeyCatalog` e `AppShortcutCatalog`:

- **POWER:** `KEY_POWER`
- **VOLUME:** `KEY_VOLUP`, `KEY_VOLDOWN`, `KEY_MUTE`
- **NAV (D-pad):** `KEY_UP/DOWN/LEFT/RIGHT`, `KEY_ENTER`, `KEY_HOME`, `KEY_RETURN`, `KEY_MENU`
- **MEDIA:** `KEY_PLAY`, `KEY_PAUSE`, `KEY_STOP`, `KEY_REW`, `KEY_FF`
- **NUMERIC:** `KEY_0`..`KEY_9`
- **SHORTCUT:** `KEY_CHUP`, `KEY_CHDOWN`, `KEY_SOURCE`, `KEY_INFO`
- **Apps de streaming (atalhos):** Netflix (`11101200001`), Prime Video
  (`3201910019365`), Disney+ (`3201901017640`), YouTube (`111299001912`).
  `findByAppIdOrFallback` retorna um fallback configurável (padrão: Netflix) para IDs
  desconhecidos; o catálogo é estendido apenas adicionando entradas à lista.

## 12. Permissões Android (LAN)

Declaradas em `AndroidManifest.xml` — todas de rede, nenhuma sensível/perigosa:

- `INTERNET`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE` — sockets e estado da rede.
- `CHANGE_WIFI_MULTICAST_STATE` — necessária para SSDP/mDNS (multicast UDP).

`minSdk` 26 (Android 8.0). Nenhuma permissão de localização, armazenamento ou
telemetria — coerente com o princípio de operação 100% LAN.

## 13. Estratégia de testes

Há **duas** suítes complementares:

1. **`tests/*.py` (pytest)** — runner de CI da fábrica. Cada arquivo cobre uma tarefa
   concluída (ex.: `test_tizen_protocol.py`, `test_remote_wake_on_lan.py`,
   `test_protocol_contract.py`). Quando há toolchain Kotlin nas caches do Gradle, os
   testes compilam e executam o código Kotlin real (com um shim de `org.json` quando
   necessário); senão fazem verificação estrutural e dão `skip` em vez de falhar.
2. **Testes nativos Android** — `app/src/test` (unitários JVM, transporte mockado via
   `CommandTransport`) e `app/src/androidTest` (Room `KnownTvDaoTest` e Compose UI com
   `RemoteTestTags`, incluindo acessibilidade/TalkBack).

`tests/contracts/tizen_protocol_v2.json` é o contrato golden de fio (§9).

Há ainda uma verificação **end-to-end de build e inicialização**
(`tests/test_app_build_and_launch_e2e.py`): checagens estruturais rápidas garantem
que a única activity exportada é a `MainActivity` LAUNCHER e que o host de navegação
parte de `Screen.Discovery`; testes lentos (marcados `slow`) rodam `:app:build`
exigindo `BUILD SUCCESSFUL` e, havendo device/emulador, instalam via
`:app:installDebug`, lançam o app, confirmam que a `MainActivity` é a activity
resumida, varrem o logcat por `FATAL EXCEPTION` e validam via `uiautomator` que a
tela de descoberta foi renderizada. Sem device, esses testes dão `skip`.

## 14. Navegação e composição de telas (host)

O app é **single-activity**: `MainActivity` (`@AndroidEntryPoint`) hospeda todo o
fluxo em Compose. O destino atual é a própria **fonte de verdade de navegação**,
modelado por uma `sealed interface Screen`:

```
Screen.Discovery ──onTvSelected(tv)──▶ Screen.Pairing(tv)
                                            │
                                  onPaired(token)
                                            ▼
                               Screen.Remote(tv, token)
```

- O estado inicial é `Screen.Discovery` (`remember { mutableStateOf<Screen>(...) }`).
- A TV escolhida (`DiscoveredTv`) e o token de pareamento são **carregados adiante
  como parte do estado de navegação** — `Screen.Pairing` leva a `tv`, `Screen.Remote`
  leva `tv` + `token` — em vez de um canal lateral. `RemoteRoute` replaya o token para
  abrir a sessão e ligar os controles à TV.
- **Padrão Route/Screen.** Cada tela é um par: um `*Route` *stateful* (coleta o
  `StateFlow` do ViewModel via Hilt e expõe callbacks de navegação) que delega a um
  `*Screen` *stateless* (recebe estado + lambdas), mantendo a UI pura testável em
  isolamento (Compose UI tests com `RemoteTestTags`). Cada `*Screen` renderiza seu
  próprio `Scaffold`; o host apenas troca o destino corrente.
- A dependência `androidx.navigation:navigation-compose` (+ `hilt-navigation-compose`)
  está disponível no catálogo para evolução do grafo de navegação; o host atual usa um
  estado selado enxuto, suficiente para o fluxo linear de três telas.

> **Status de implementação (2026-06-02).** Todas as camadas descritas neste documento
> estão implementadas e ligadas de ponta a ponta: descoberta (SSDP+mDNS+REST+
> reconciliação), pareamento com TLS LAN, sessão WebSocket com reconexão, protocolo
> Tizen, catálogos completos de teclas/atalhos, Wake-on-LAN, persistência cifrada e o
> fluxo de navegação Discovery → Pairing → Remote (§14) ligado no `MainActivity` e
> coberto pela verificação e2e de build/inicialização.

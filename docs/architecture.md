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
| **UI (Compose)** | Telas: descoberta de TVs, pareamento, controle (D-pad, volume, teclado, atalhos) | Kotlin, Jetpack Compose, Material 3 |
| **ViewModels** | Estado de tela, mapeia toques → intents, expõe `StateFlow` | Kotlin, AndroidX ViewModel, Coroutines/Flow |
| **DiscoveryService** | Localiza TVs Samsung na LAN via SSDP/mDNS e valida via endpoint REST `/api/v2/` | Kotlin, SSDP (UDP multicast), OkHttp |
| **PairingManager** | Handshake e obtenção/renovação do token de autorização | OkHttp WebSocket |
| **RemoteSession** | Conexão WebSocket persistente; envia `RemoteKey`, recebe eventos; reconexão | OkHttp WebSocket, Coroutines |
| **CommandRepository** | API de domínio (`sendKey`, `sendText`, `launchApp`); mapeia teclas/atalhos para o protocolo Tizen | Kotlin |
| **TvRegistry** | Persiste TVs conhecidas e seus tokens | Room + Jetpack Security (EncryptedSharedPreferences/Tink) |

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
    ui/
      discovery/        # tela de descoberta de TVs
      pairing/          # tela de pareamento
      remote/           # tela do controle (dpad, volume, teclado, atalhos)
      theme/            # Material 3 theme
    viewmodel/
      DiscoveryViewModel.kt
      RemoteViewModel.kt
    data/
      repository/CommandRepository.kt
      registry/TvRegistry.kt
      db/                # Room: KnownTvDao, AppDatabase
      crypto/            # cifragem do token
    network/
      discovery/DiscoveryService.kt
      pairing/PairingManager.kt
      session/RemoteSession.kt
      protocol/          # RemoteKey, AppShortcut, mensagens Tizen
    di/                  # módulos de injeção (Hilt)
  src/test/             # testes unitários (transporte mockado)
  src/androidTest/      # testes instrumentados
docs/
  architecture.md
  decisions.md
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

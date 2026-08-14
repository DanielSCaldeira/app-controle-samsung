# dist/ — APKs prontos para instalar

Esta pasta guarda as builds **release assinadas** do app, prontas para instalar no
celular sem precisar compilar nada.

| Arquivo | Versão | Tamanho | Mínimo |
|---------|--------|---------|--------|
| [`controle-samsung-v1.0.0.apk`](controle-samsung-v1.0.0.apk) | 1.0.0 (`versionCode` 1) | ~12 MB | Android 8.0 (API 26) |

**Como baixar:** abra o arquivo acima e clique em **Download raw file** (ícone de download
no canto superior direito). O repositório é privado — é preciso estar **logado no GitHub**
com uma conta que tenha acesso.

Instruções completas de instalação na seção
[📥 Baixar e instalar](../README.md#-baixar-e-instalar) do README principal.

---

## Como uma nova versão entra aqui

1. Ajuste `versionCode` / `versionName` em [`app/build.gradle.kts`](../app/build.gradle.kts).
2. `make assemble-release` (ou `./gradlew.bat :app:assembleRelease`).
3. Copie `app/build/outputs/apk/release/app-release.apk` para cá como
   `controle-samsung-v<versao>.apk`.
4. Atualize os links do README principal e publique o
   [Release](https://github.com/DanielSCaldeira/app-controle-samsung/releases) com o APK.

> A assinatura sai do keystore descrito em `keystore.properties` (arquivo local, não
> versionado). **Todas as versões precisam usar o mesmo keystore** — trocar a chave
> impede a atualização por cima do app já instalado.

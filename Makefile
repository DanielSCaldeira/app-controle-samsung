# Makefile para fluxo Android (Windows)
# Uso:
#   make help
#   make run                  # instala no dispositivo conectado e abre o app
#   make run SERIAL=0080028452  # mira um dispositivo especifico (veja 'make adb-devices')
#   make screenshot SHOT=tela.png
#
# Requisitos:
# - GNU Make instalado
# - Android SDK + adb no PATH
# - Java 17

SHELL := /bin/sh

GRADLEW ?= gradlew.bat
APP_ID ?= com.factory.samsungremote
MAIN_ACTIVITY ?= .MainActivity

# Emulador (ajuste AVD para o nome da sua imagem; veja 'make list-avds')
EMULATOR ?= "$(LOCALAPPDATA)/Android/Sdk/emulator/emulator.exe"
AVD ?= Medium_Phone_API_36.1

# Dispositivo alvo. Com mais de um conectado (ex.: emulador + celular), passe
# SERIAL=<serial> (obtido em 'make adb-devices') para mirar um especifico;
# caso contrario os comandos usam o unico dispositivo conectado.
SERIAL ?=
ADB ?= adb
ADBT := $(ADB) $(if $(SERIAL),-s $(SERIAL),)
GRADLE_SERIAL := $(if $(SERIAL),ANDROID_SERIAL=$(SERIAL) ,)

# Arquivo de saida para 'make screenshot'.
SHOT ?= screenshot.png

.PHONY: \
	help tasks doctor \
	clean rebuild build fresh \
	assemble assemble-debug assemble-release \
	check-device wait-device list-avds emulator run restart \
	install install-debug uninstall-debug \
	test test-debug test-release \
	android-test connected-check \
	lint lint-debug lint-release \
	signing-report dependencies \
	adb-devices adb-logcat logcat-app screenshot app-start app-stop

help: ## Mostra esta ajuda com todos os comandos e explicacoes
	@echo Comandos disponiveis:
	@echo   help                   Mostra esta ajuda com todos os comandos e explicacoes
	@echo   tasks                  Lista todas as tasks disponiveis no modulo app
	@echo   doctor                 Checa ambiente basico: Java, adb e dispositivos conectados
	@echo   clean                  Limpa arquivos de build
	@echo   rebuild                Limpa e compila novamente
	@echo   build                  Compila e roda verificacoes do app
	@echo   fresh                  Build limpo ignorando caches - resolve dex/KSP corrompido - e instala
	@echo   assemble               Gera APK/AAB das variantes configuradas
	@echo   assemble-debug         Gera APK debug
	@echo   assemble-release       Gera APK release
	@echo   check-device           Verifica se ha ao menos um dispositivo/emulador conectado
	@echo   wait-device            Aguarda um dispositivo/emulador ficar pronto - boot completo
	@echo   list-avds              Lista os emuladores AVDs disponiveis
	@echo   emulator               Sobe o emulador padrao AVD em segundo plano
	@echo   run                    Instala o app debug e ja abre no dispositivo conectado
	@echo   restart                Fecha e reabre o app no dispositivo conectado
	@echo   install                Alias para instalar a versao debug
	@echo   install-debug          Compila e instala o app no celular/emulador conectado
	@echo   uninstall-debug        Remove o app debug do dispositivo conectado
	@echo   test                   Roda testes unitarios de todas as variantes
	@echo   test-debug             Roda testes unitarios da variante debug
	@echo   test-release           Roda testes unitarios da variante release
	@echo   android-test           Instala e executa testes instrumentados no dispositivo conectado
	@echo   connected-check        Executa todas as verificacoes em dispositivo conectado
	@echo   lint                   Roda lint da variante padrao
	@echo   lint-debug             Roda lint da variante debug
	@echo   lint-release           Roda lint da variante release
	@echo   signing-report         Exibe informacoes de assinatura das builds
	@echo   dependencies           Lista dependencias do modulo app
	@echo   adb-devices            Lista dispositivos Android conectados
	@echo   adb-logcat             Mostra todos os logs em tempo real - Ctrl+C para parar
	@echo   logcat-app             Mostra apenas os logs do app - Ctrl+C para parar
	@echo   screenshot             Captura a tela do dispositivo - use SHOT=arquivo.png
	@echo   app-start              Abre o app no dispositivo conectado
	@echo   app-stop               Fecha o app no dispositivo conectado
	@echo .
	@echo   Dica: com varios dispositivos, acrescente SERIAL=seu_serial  -  ex: make run SERIAL=0080028452

tasks: ## Lista todas as tasks disponiveis no modulo app
	@$(GRADLEW) :app:tasks --all

doctor: ## Checa ambiente basico: Java, adb e dispositivos conectados
	@java -version || true
	@$(ADB) version || true
	@$(ADB) devices || true

clean: ## Limpa arquivos de build
	@$(GRADLEW) :app:clean

rebuild: clean build ## Limpa e compila novamente

build: ## Compila e roda verificacoes do app
	@$(GRADLEW) :app:build

fresh: check-device ## Build limpo ignorando caches (resolve dex/KSP corrompido) e instala
	@echo "Parando daemons do Gradle..."; $(GRADLEW) --stop || true
	@echo "Limpando build do modulo..."; $(GRADLEW) :app:clean
	@echo "Instalando do zero (sem cache)..."; $(GRADLE_SERIAL)$(GRADLEW) :app:installDebug --no-build-cache

assemble: ## Gera APK/AAB das variantes configuradas
	@$(GRADLEW) :app:assemble

assemble-debug: ## Gera APK debug
	@$(GRADLEW) :app:assembleDebug

assemble-release: ## Gera APK release
	@$(GRADLEW) :app:assembleRelease

check-device: ## Verifica se ha ao menos um dispositivo/emulador conectado
	@count=`$(ADBT) devices | grep -w device | wc -l`; \
	if [ "$$count" -lt 1 ]; then \
		echo "============================================================"; \
		echo "Nenhum dispositivo/emulador conectado foi detectado."; \
		echo ""; \
		echo "Para instalar o app, faca o seguinte:"; \
		echo "  1) Conecte o celular via USB com a depuracao USB ativada"; \
		echo "     (Configuracoes > Opcoes do desenvolvedor > Depuracao USB)."; \
		echo "  2) Autorize o prompt 'Permitir depuracao USB?' na tela do celular."; \
		echo "  3) Rode 'make adb-devices' (ou 'make doctor') para confirmar"; \
		echo "     que o dispositivo aparece como 'device'."; \
		echo "  4) Tente novamente: 'make install-debug'."; \
		echo "     (com varios dispositivos, use SERIAL=<serial>)"; \
		echo "============================================================"; \
		exit 1; \
	fi

wait-device: ## Aguarda um dispositivo/emulador ficar pronto (boot completo)
	@echo "Aguardando dispositivo..."; \
	$(ADBT) wait-for-device; \
	while [ "`$(ADBT) shell getprop sys.boot_completed 2>/dev/null | tr -d '\r'`" != "1" ]; do sleep 2; done; \
	echo "Dispositivo pronto."; $(ADBT) devices

list-avds: ## Lista os emuladores (AVDs) disponiveis
	@$(EMULATOR) -list-avds

emulator: ## Sobe o emulador padrao (AVD) em segundo plano
	@echo "Subindo emulador $(AVD)..."; \
	$(EMULATOR) -avd $(AVD) -netdelay none -netspeed full &

run: install-debug app-start ## Instala o app debug e ja abre no dispositivo conectado

restart: ## Fecha e reabre o app no dispositivo conectado
	@$(ADBT) shell am force-stop $(APP_ID)
	@$(ADBT) shell am start -n $(APP_ID)/$(MAIN_ACTIVITY)

install: install-debug ## Alias para instalar a versao debug

install-debug: check-device ## Compila e instala o app no celular/emulador conectado
	@$(GRADLE_SERIAL)$(GRADLEW) :app:installDebug

uninstall-debug: ## Remove o app debug do dispositivo conectado
	@$(GRADLE_SERIAL)$(GRADLEW) :app:uninstallDebug

test: ## Roda testes unitarios de todas as variantes
	@$(GRADLEW) :app:test

test-debug: ## Roda testes unitarios da variante debug
	@$(GRADLEW) :app:testDebugUnitTest

test-release: ## Roda testes unitarios da variante release
	@$(GRADLEW) :app:testReleaseUnitTest

android-test: check-device ## Instala e executa testes instrumentados no dispositivo conectado
	@$(GRADLE_SERIAL)$(GRADLEW) :app:connectedDebugAndroidTest

connected-check: check-device ## Executa todas as verificacoes em dispositivo conectado
	@$(GRADLE_SERIAL)$(GRADLEW) :app:connectedCheck

lint: ## Roda lint da variante padrao
	@$(GRADLEW) :app:lint

lint-debug: ## Roda lint da variante debug
	@$(GRADLEW) :app:lintDebug

lint-release: ## Roda lint da variante release
	@$(GRADLEW) :app:lintRelease

signing-report: ## Exibe informacoes de assinatura das builds
	@$(GRADLEW) :app:signingReport

dependencies: ## Lista dependencias do modulo app
	@$(GRADLEW) :app:dependencies

adb-devices: ## Lista dispositivos Android conectados
	@$(ADB) devices -l

adb-logcat: ## Mostra todos os logs em tempo real (Ctrl+C para parar)
	@$(ADBT) logcat

logcat-app: ## Mostra apenas os logs do app (Ctrl+C para parar)
	@pid=`$(ADBT) shell pidof -s $(APP_ID) 2>/dev/null | tr -d '\r'`; \
	if [ -n "$$pid" ]; then \
		echo "Logs de $(APP_ID) (pid $$pid):"; $(ADBT) logcat --pid=$$pid; \
	else \
		echo "App nao esta rodando. Abra com 'make app-start' e tente de novo."; \
	fi

screenshot: ## Captura a tela do dispositivo (use SHOT=arquivo.png)
	@$(ADBT) exec-out screencap -p > "$(SHOT)"; \
	echo "Screenshot salvo em $(SHOT)"

app-start: ## Abre o app no dispositivo conectado
	@$(ADBT) shell am start -n $(APP_ID)/$(MAIN_ACTIVITY)

app-stop: ## Fecha o app no dispositivo conectado
	@$(ADBT) shell am force-stop $(APP_ID)

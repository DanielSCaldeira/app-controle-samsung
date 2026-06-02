# Makefile para fluxo Android (Windows)
# Uso:
#   make help
#   make install-debug
#
# Requisitos:
# - GNU Make instalado
# - Android SDK + adb no PATH
# - Java 17

SHELL := /bin/sh

GRADLEW ?= gradlew.bat
APP_ID ?= com.factory.samsungremote

.PHONY: \
	help tasks doctor \
	clean rebuild build \
	assemble assemble-debug assemble-release \
	install install-debug uninstall-debug \
	test test-debug test-release \
	android-test connected-check \
	lint lint-debug lint-release \
	signing-report dependencies \
	adb-devices adb-logcat app-start app-stop

help: ## Mostra esta ajuda com todos os comandos e explicacoes
	@echo Comandos disponiveis:
	@echo   help                   Mostra esta ajuda com todos os comandos e explicacoes
	@echo   tasks                  Lista todas as tasks disponiveis no modulo app
	@echo   doctor                 Checa ambiente basico: Java, adb e dispositivos conectados
	@echo   clean                  Limpa arquivos de build
	@echo   rebuild                Limpa e compila novamente
	@echo   build                  Compila e roda verificacoes do app
	@echo   assemble               Gera APK/AAB das variantes configuradas
	@echo   assemble-debug         Gera APK debug
	@echo   assemble-release       Gera APK release
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
	@echo   adb-logcat             Mostra logs em tempo real (Ctrl+C para parar)
	@echo   app-start              Abre o app no dispositivo conectado
	@echo   app-stop               Fecha o app no dispositivo conectado

tasks: ## Lista todas as tasks disponiveis no modulo app
	@$(GRADLEW) :app:tasks --all

doctor: ## Checa ambiente basico: Java, adb e dispositivos conectados
	@java -version || true
	@adb version || true
	@adb devices || true

clean: ## Limpa arquivos de build
	@$(GRADLEW) :app:clean

rebuild: clean build ## Limpa e compila novamente

build: ## Compila e roda verificacoes do app
	@$(GRADLEW) :app:build

assemble: ## Gera APK/AAB das variantes configuradas
	@$(GRADLEW) :app:assemble

assemble-debug: ## Gera APK debug
	@$(GRADLEW) :app:assembleDebug

assemble-release: ## Gera APK release
	@$(GRADLEW) :app:assembleRelease

install: install-debug ## Alias para instalar a versao debug

install-debug: ## Compila e instala o app no celular/emulador conectado
	@$(GRADLEW) :app:installDebug

uninstall-debug: ## Remove o app debug do dispositivo conectado
	@$(GRADLEW) :app:uninstallDebug

test: ## Roda testes unitarios de todas as variantes
	@$(GRADLEW) :app:test

test-debug: ## Roda testes unitarios da variante debug
	@$(GRADLEW) :app:testDebugUnitTest

test-release: ## Roda testes unitarios da variante release
	@$(GRADLEW) :app:testReleaseUnitTest

android-test: ## Instala e executa testes instrumentados no dispositivo conectado
	@$(GRADLEW) :app:connectedDebugAndroidTest

connected-check: ## Executa todas as verificacoes em dispositivo conectado
	@$(GRADLEW) :app:connectedCheck

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
	@adb devices

adb-logcat: ## Mostra logs em tempo real (Ctrl+C para parar)
	@adb logcat

app-start: ## Abre o app no dispositivo conectado
	@adb shell monkey -p $(APP_ID) -c android.intent.category.LAUNCHER 1

app-stop: ## Fecha o app no dispositivo conectado
	@adb shell am force-stop $(APP_ID)

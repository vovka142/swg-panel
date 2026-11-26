# swg-sub в нативном варианте — публичная поверхность подписок.
#
# Этот код вынесен в отдельный файл, потому что это самостоятельная ГРАНИЦА БЕЗОПАСНОСТИ
# (docs/NIXOS-SUPPORT-PLAN.md D8), а не потому, что panel.nix стал слишком длинным. Это единственный
# процесс во всей системе, которому намеренно разрешён доступ из интернета. Он отделён от панели сразу
# по четырём параметрам: отдельный пользователь, файловая система только для чтения, собственные
# TLS-данные и маскирование секретов на уровне ядра, к которым ему запрещено обращаться. Передача
# приватного TLS-ключа панели интернет-доступному процессу позволила бы при его компрометации выдавать себя за панель.
#
# ⚠️⚠️ Раньше в репозитории находилась копия `systemd/swg-sub.service` для справки. ЕЁ УДАЛИЛИ
# (2026-08-24, Z-11), а не просто снабдили комментарием. Это пояснение оставлено, чтобы никто не
# восстановил её из истории, посчитав удаление случайностью. В ней было `User=swgpanel` — учётная запись
# САМОЙ ПАНЕЛИ, `SWG_SUB_TLS_KEY=/etc/swg-panel/tls/key.pem` и полностью отсутствовала строка
# `InaccessiblePaths`. Использование такого файла разрушило бы все три границы безопасности сразу —
# именно на том участке, где каждая из них критически важна. Поддерживать «эталонную копию» в соответствии
# с генератором означает иметь второе описание того же контракта — один из самых частых классов ошибок
# в этом репозитории. Сейчас контракт описан только в двух местах: генерируемом unit (`write_sub_unit` в install-host.sh) и этом модуле; они согласованы.
#
# Параметры находятся в panel.nix внутри `services.swg-panel.sub`: поверхность подписок без панели
# не имеет смысла, поскольку читает состояние панели.
{ config, lib, pkgs, ... }:

let
  cfg = config.services.swg-panel;
  sub = cfg.sub;
  inherit (lib) mkIf optional optionalString;

  stateDir = cfg.stateDir;
  etcDir = cfg.configDir;

  # Шесть путей, которые этот процесс не должен иметь возможности открыть. Префикс `-` позволяет
  # запустить систему, даже если какого-либо пути пока нет. Доступ блокируется на уровне ЯДРА, а не
  # только правами файлов: даже ошибка в процессе не позволит ему получить доступ при неверных разрешениях.
  #
  #    хеш пароля · TLS-ключ ПАНЕЛИ (не этого процесса) · хранилище ключей подписок
  #    (один ключ раскрывает ключи всех узлов) · ключи разблокировки и токены пользователей, обёрнутые SK ·
  #    секреты подписи webhook и хеши API-токенов · сохранённые клиентские конфигурации
  #
  # swg-sub не читает НИ ОДИН из этих файлов; настройки он получает из subs/serve.json. Ключ разблокировки
  # передаётся во фрагменте URL и никогда не отправляется серверу, поэтому процесс может отдавать только
  # шифротекст и несекретные параметры — но не приватный ключ и не данные всей инфраструктуры.
  masked = [
    "-${etcDir}/auth"
    "-${etcDir}/tls"
    "-${stateDir}/subs/vault.json"
    "-${stateDir}/subs/escrow.json"
    "-${stateDir}/panel-settings.json"
    "-${stateDir}/configs"
  ];

in
{
  config = mkIf (cfg.enable && cfg.delivery == "native" && sub.enable) {
    users.users.swgsub = {
      isSystemUser = true;
      # Группа swg — это весь доступ на чтение, который ему предоставлен: состояние панели имеет права 0750
      # и владельца swgpanel:swg. Членство в группе позволяет проходить по каталогам к разрешённым файлам,
      # но файлы с доступом только владельцу (0600) остаются закрытыми. Пользователь намеренно отличается
      # от пользователя панели: повторное использование swgpanel уничтожило бы эту границу, хотя всё остальное работало бы.
      group = "swg";
      description = "swg subscription surface (public, read-only)";
    };

    # СОБСТВЕННЫЙ каталог сертификатов. Не каталог панели — он замаскирован выше.
    systemd.tmpfiles.rules = [ "d ${cfg.subTlsDir} 0750 root swg -" ];

    systemd.services.swg-sub = {
      description = "swg-sub — public per-user subscription surface (read-only)";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];

      environment = {
        SWG_SUB_FLEET = "${etcDir}/fleet.json";
        SWG_SUB_WEB = "${cfg.package}/libexec/swg-sub";
        SWG_SUB_HOST = sub.host;
        SWG_SUB_PORT = toString sub.port;
        SWG_SUB_BASE = sub.basePath;
        SWG_SUB_TLS_DIR = cfg.subTlsDir;
        SWG_SUB_TRUST_XFF = if sub.trustProxyHeaders then "1" else "0";
      };

      serviceConfig = {
        Type = "simple";
        User = "swgsub";
        # Явно задано, в отличие от генерируемого unit панели, который указывает только User= и полагается
        # на основную группу учётной записи. В unit swg-sub установщик задаёт оба параметра, как и здесь.
        Group = "swg";
        ExecStart = "${cfg.package}/libexec/swg-sub/swg-sub";
        Restart = "on-failure";
        RestartSec = 2;

        # ── полный набор ограничений безопасности ──
        # ⚠️ `ReadWritePaths` намеренно НЕ задан. Процесс ничего не записывает, поэтому при
        # `ProtectSystem=strict` вся файловая система доступна ему только для чтения. Добавление исключения
        # «только для журналов» или «только для кэша» разрушило бы это свойство.
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectControlGroups = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        RestrictNamespaces = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        InaccessiblePaths = masked;
      } // lib.optionalAttrs (sub.port < 1024) {
        # Установщик добавляет эту настройку при установке swg-sub на привилегированный порт, а drop-in
        # от swg-netctl добавляет её повторно, когда панель переводит сервис на такой порт.
        AmbientCapabilities = [ "CAP_NET_BIND_SERVICE" ];
      };
    };
  };
}

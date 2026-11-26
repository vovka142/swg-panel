# swg-panel — все программы и веб-ресурсы полной установки в ОДНОМ пути хранилища.
#
# Одна derivation, а не три, поскольку репозиторий — единое целое: VERSION — единственный источник версии,
# которая записывается во все компоненты (CLAUDE.md). Разделение пакета привело бы к расхождению версий
# уже после следующей пересборки. По той же причине модуль NixOS находится в этом репозитории, а не в отдельном
# репозитории вроде foo-nix (docs/NIXOS-SUPPORT-PLAN.md D1).
#
# ── почему структура повторяет /opt и почему в $out/bin находятся обёртки, а не символические ссылки ──
# Две наши программы ищут файлы ОТНОСИТЕЛЬНО СОБСТВЕННОГО РАСПОЛОЖЕНИЯ:
#     swg-noded    dirname(__file__)/VERSION        и  dirname(argv[0])/swg-sni
#     panel / sub  $SWG_{PANEL,SUB}_WEB/VERSION  →  dirname(__file__)/VERSION
# поэтому программа и её данные должны находиться в одном каталоге — отсюда $out/libexec/<component>/,
# копия в store-пути того, что установщики размещают в /opt/<component>/.
# Элементы bin ВЫПОЛНЯЮТ файлы из libexec вместо создания ссылок на них: для скрипта по символической ссылке
# ядро передаёт интерпретатору путь ССЫЛКИ, поэтому argv[0]/__file__ указывали бы на $out/bin,
# и оба поиска выше незаметно завершились бы неудачей (VERSION оказался бы пустым, swg-sni — «не найден»).
#
# ── манифест ──
# panelWeb/subWeb ниже — ЧЕТВЁРТОЕ место в этом дереве, где перечислены поставляемые ресурсы. Остальные —
# строки COPY в Dockerfile, SUB_WEB в lib/common.sh и карта STATIC самого swg-sub. Если добавить файл
# не во все списки, ошибка проявится только при НОВОЙ сборке или установке — именно так 3b731f7 попал в CI.
# Файл `.campaign/shipped-assets-audit.mjs` синхронизирует все четыре списка; запускайте его
# при каждом добавлении или удалении ресурса.
{ lib
, stdenvNoCC
, python3
, runtimeShell
  # Корень дерева исходников. По умолчанию — родительский каталог этого файла, чтобы модуль мог вызвать
  # `./package.nix { }` через `callPackage` с pkgs ПОТРЕБИТЕЛЯ (D1), не передавая src отдельно.
, srcRoot ? ../.
  # ИДЕНТИФИКАТОР СБОРКИ, который будет показан в панели. Все остальные варианты установки записывают
  # коммит в VERSION; вариант Nix устанавливал исходный файл `VERSION`, поэтому две разные сборки одной ветки
  # обе показывали `1.8.6-beta`, и панель не могла отличить узел со вчерашним кодом от узла с сегодняшним.
  # Параметр необязательный и имеет значение по умолчанию, поэтому собственный вызов модуля
  # `callPackage ./package.nix { }` (D1) не меняется: без переданного rev потребитель получает прежнее поведение.
, rev ? ""
}:

let
  fs = lib.fileset;

  baseVersion = lib.fileContents (srcRoot + "/VERSION");
  # `1.8.6-beta+ab12cd3` — тот же формат, который записывают install-host.sh и образы Docker, поэтому
  # существующему механизму чтения версии в панели не требуется отдельная логика для Nix.
  version = baseVersion + lib.optionalString (rev != "") ("+" + rev);

  # Корневой каталог веб-файлов панели — соответствует циклу копирования в install-host.sh
  # ("index.html app.css app.js reconcile.js turn-artifacts.js") и первой команде COPY в Dockerfile.
  panelWeb = [ "index.html" "app.css" "app.js" "reconcile.js" "turn-artifacts.js" ];

  # Список разрешённых статических файлов swg-sub. Побайтно совпадает с SUB_WEB в lib/common.sh
  # и сохраняет тот же порядок — так любое расхождение будет видно в однострочном diff.
  subWeb = [ "sub.html" "sub.js" "sub.css" "turn-artifacts.js" ];

  # Каталоги копируются целиком, как в установщиках и Dockerfile. Поэтому добавление
  # модуля или шрифта не требует изменения этого файла.
  trees = [ "js" "m" "vendor" ];

  programs = [
    "swg-panel-server"   # the panel: UI + node-sync API
    "swg-sub"            # the public subscription surface — its own user and unit (D8)
    "swg-noded"          # node daemon
    "swg-sni"            # SNI classifier, launched by swg-noded from its own directory
    "swg-relay"          # TCP-terminating relay, launched by swg-noded from its own directory
    "swg-agent"          # one peer op, stdin → stdout
    "swg-netctl"         # Access/TLS helper, root-side of the panel's queue
    "swg-passwd"         # `swg-passwd` — reset the panel login
    "swg-logs"           # `swg-logs` — read swg's journals by source name
  ];

  # lib.fileset выдаёт ошибку, если путь не существует. Поэтому потеря поставляемого файла из-за .gitignore
  # или переименования приводит к ошибке ВЫЧИСЛЕНИЯ, а не к незаметно неполному store-пути (V.6b).
  shipped = fs.unions (map (p: srcRoot + "/${p}")
    ([ "VERSION" "docker/node-entrypoint.sh" ] ++ programs ++ trees ++ panelWeb ++ subWeb));

in
stdenvNoCC.mkDerivation {
  pname = "swg-panel";
  inherit version;

  src = fs.toSource { root = srcRoot; fileset = shipped; };

  # python3 — зависимость для ЦЕЛЕВОЙ СИСТЕМЫ, а не для сборочной: patchShebangs --host заменяет
  # `#!/usr/bin/env python3` на этот интерпретатор, поэтому каждая программа получает собственный путь к нему.
  # Во время этапа A работы над NixOS выяснилось, что python3 отсутствовал в системном профиле узла,
  # а сбой был незаметным: программа с неразрешимым shebang просто не запускается. Теперь это исключено.
  # (node-entrypoint.sh по-прежнему вызывает `python3` из PATH, поэтому он тоже нужен в `path` модуля.)
  buildInputs = [ python3 ];

  dontBuild = true;
  dontConfigure = true;

  installPhase = ''
    runHook preInstall

    # Версия, которую читает каждый компонент; к ней добавляется ревизия сборки, если она была передана.
    # ⚠️ Используется `echo`, а не `printf '%s\n'`: строка Nix с отступами передаёт обратные слеши без изменений,
    # поэтому вариант с printf записал бы в файл буквальные символы `\n`, и версия каждого компонента
    # заканчивалась бы на backslash-n. Значение записывается один раз и устанавливается в трёх местах.
    echo "$version" > VERSION.stamped

    # ── панель: программа + SPA + VERSION в одном каталоге ──
    install -Dm755 swg-panel-server $out/libexec/swg-panel/swg-panel-server
    install -Dm644 VERSION.stamped  $out/libexec/swg-panel/VERSION
    for f in ${lib.concatStringsSep " " panelWeb}; do
      install -Dm644 "$f" "$out/libexec/swg-panel/$f"
    done
    ${lib.concatMapStringsSep "\n    " (d: "cp -R --no-preserve=mode ${d} $out/libexec/swg-panel/${d}") trees}

    # ── swg-sub: отдельный каталог и копия VERSION (отдельные unit, пользователь и каталог TLS) ──
    install -Dm755 swg-sub          $out/libexec/swg-sub/swg-sub
    install -Dm644 VERSION.stamped  $out/libexec/swg-sub/VERSION
    for f in ${lib.concatStringsSep " " subWeb}; do
      install -Dm644 "$f" "$out/libexec/swg-sub/$f"
    done
    install -Dm644 vendor/qrcode.js $out/libexec/swg-sub/vendor/qrcode.js

    # ── узел: swg-sni находится рядом с swg-noded, поскольку именно там его ищут в первую очередь ──
    install -Dm755 swg-noded        $out/libexec/swg-noded/swg-noded
    install -Dm755 swg-sni          $out/libexec/swg-noded/swg-sni
    install -Dm755 swg-relay        $out/libexec/swg-noded/swg-relay
    install -Dm644 VERSION.stamped  $out/libexec/swg-noded/VERSION

    install -Dm755 swg-agent        $out/libexec/swg-agent/swg-agent

    # Начальная настройка узла: создаёт config.json, поднимает все сохранённые интерфейсы до запуска
    # демона и настраивает NAT. Файл без изменений используется и контейнерным вариантом (D15) —
    # нативный unit запускает его непосредственно из store.
    install -Dm755 docker/node-entrypoint.sh $out/libexec/swg-node/node-entrypoint.sh

    # ── $out/bin ──
    # swg-netctl и swg-passwd не ищут файлы относительно собственного расположения, поэтому это реальные файлы.
    install -Dm755 swg-netctl $out/bin/swg-netctl
    install -Dm755 swg-passwd $out/bin/swg-passwd
    install -Dm755 swg-logs   $out/bin/swg-logs

    # Для остальных создаются обёртки, выполняющие файл из libexec: так интерпретатор получает этот путь
    # в argv[0]/__file__, и поиск соседних файлов работает. См. пояснение в начале файла.
    mkbin() {
      printf '#!%s\nexec %s "$@"\n' "${runtimeShell}" "$2" > "$out/bin/$1"
      chmod 755 "$out/bin/$1"
    }
    mkbin swg-panel-server $out/libexec/swg-panel/swg-panel-server
    mkbin swg-sub          $out/libexec/swg-sub/swg-sub
    mkbin swg-noded        $out/libexec/swg-noded/swg-noded
    mkbin swg-sni          $out/libexec/swg-noded/swg-sni
    mkbin swg-relay        $out/libexec/swg-noded/swg-relay
    mkbin swg-agent        $out/libexec/swg-agent/swg-agent

    runHook postInstall
  '';

  # --host: интерпретатор берётся из buildInputs; это также подходит для кросс-сборки.
  postFixup = ''
    patchShebangs --host $out/libexec $out/bin
  '';

  # Store-путь с незаменённым `#!/usr/bin/env python3` работал бы на машине, где выполнялась сборка,
  # но не запустился бы на системе без python3 в PATH — та же незаметная ошибка, только в другом месте.
  # Вместо этого сборка завершается ошибкой. `env` здесь допустим только в том случае, если patchShebangs его пропустил.
  doInstallCheck = true;
  installCheckPhase = ''
    bad=$(grep -rl '^#!/usr/bin/env' $out/libexec $out/bin || true)
    if [ -n "$bad" ]; then
      echo "unpatched shebang — patchShebangs did not resolve these:" >&2
      echo "$bad" >&2
      exit 1
    fi
    test -x $out/libexec/swg-noded/swg-noded
    test -s $out/libexec/swg-panel/VERSION
    test -s $out/libexec/swg-noded/VERSION
    test -s $out/libexec/swg-sub/VERSION
  '';

  meta = {
    description = "Self-hosted control panel for a small WireGuard / AmneziaWG service";
    longDescription = ''
      The panel is the source of truth for peers; each node syncs to it over outbound HTTPS only.
      This package ships all five programs plus the buildless SPA; the NixOS modules in the same
      flake decide which of them a given host runs.
    '';
    homepage = "https://github.com/SanityProtocol/swg-panel";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "swg-panel-server";
  };
}

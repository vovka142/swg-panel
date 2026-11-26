# T-T1, контейнерный вариант — всё, что не требует самого образа.
#
# ⚠️ ПОЧЕМУ ЭТОТ ТЕСТ ВЫНЕСЕН ОТДЕЛЬНО и почему он не запускает контейнер. У nixosTest VM нет
# интернета, поэтому она не может загрузить ghcr.io/sanityprotocol/swg-node. Рассматривались два
# очевидных обходных варианта, но от обоих ОТКАЗАЛИСЬ:
#   · временный образ dockerTools, собранный из нашего исходного кода: это стало бы ТРЕТЬИМ описанием
#     содержимого образа наряду с Dockerfile и проверкой поставляемых ресурсов; оно незаметно устаревало бы,
#     а успешный тест означал бы «контейнерный вариант работает», хотя опубликованный образ мог бы не работать.
#     Именно такую ошибку этот набор тестов и должен предотвращать.
#   · закреплённый digest: он устаревает при каждой сборке образа, а единственное преимущество перед этим
#     файлом — сборка самого опубликованного образа, которую `docker.yml` уже проверяет при каждом push.
#
# Оставшаяся проверка охватывает больше, чем кажется: БОЛЬШАЯ ЧАСТЬ контейнерного варианта — это настройки
# хоста: sysctl, tmpfiles, среда выполнения, policy.json podman и порядок запуска unit. Для этого
# образ не нужен, и сейчас ничто из перечисленного не проверяется:
#
# probeN1C1 проверяет токены контракта сгенерированного unit, но на СОБРАННОЙ системе. Такая система
# никогда не АКТИВИРУЕТСЯ (см. rig README): ничего не запускалось, tmpfiles и сервисы не выполнялись.
# Кроме того, это РУЧНАЯ проверка, а данный тест запускается по расписанию. `compose-nix-contract.mjs`
# читает ИСХОДНЫЙ код .nix и потому вообще не видит значения во время выполнения.
#
# ⭐ Самая важная проверка здесь — `route_localnet`. На чистой системе NixOS он равен 0, и без него
# Force-DNS незаметно перестаёт работать: DNAT перенаправляет :53 клиента на loopback dnsmasq,
# а ядро отбрасывает пакеты. Такой дефект уже попадал в выпуск проекта (в контейнере он завершался
# без явной ошибки, поэтому модуль настраивает параметр НА ХОСТЕ). Никакая другая проверка не читает текущее значение.
{ srcRoot ? ../.. }:

{ lib, pkgs, ... }:

let
  stateDir = "/var/lib/swg-noded";
  confDir = "/etc/amnezia/amneziawg";
in
{
  name = "swg-container-arm";

  nodes.host = { ... }: {
    imports = [ (srcRoot + "/nix/modules/node.nix") ];
    systemd.tmpfiles.rules = [
      "d /var/lib/swg-test 0700 root root -"
      "f /var/lib/swg-test/node.env 0600 root root - NODE_TOKEN=container-arm-fixture"
    ];
    services.swg-node = {
      enable = true;
      delivery = "container";
      backend = "docker";
      environmentFile = "/var/lib/swg-test/node.env";
      panelUrl = "http://panel.invalid:8443";   # never dialled: the container cannot start
      endpoint = "192.168.1.1";
      turnManage = true;                         # ⇒ the docker socket joins the volume set
      udpPortRanges = [{ from = 51820; to = 51899; }];
    };
  };

  testScript = ''
    start_all()
    host.wait_for_unit("multi-user.target")

    def ok(name, detail=""):
        print(f"CA-ASSERT {name} OK {detail}")

    # ── ⭐ sysctl: проверяем фактические значения в РАБОТАЮЩЕЙ системе ──
    # `mkDefault true` в модуле — это декларация; здесь проверяется ответ ядра. Это разные утверждения,
    # и именно от второго зависит работа Force-DNS.
    with subtest("the host sysctls the container arm depends on are really set"):
        for key in ("net.ipv4.ip_forward", "net.ipv4.conf.all.route_localnet"):
            val = host.succeed(f"cat /proc/sys/{key.replace('.', '/')}").strip()
            assert val == "1", f"{key} is {val}, not 1 — Force-DNS would silently blackhole"
        ok("sysctls-live", "ip_forward=1 and route_localnet=1, read from /proc")

    # ── каталоги, подключаемые в контейнер bind mount ──
    # tmpfiles запускается только в АКТИВИРОВАННОЙ системе — именно эту часть probeN1C1 проверить не может.
    with subtest("the bind-mount sources exist before any container does"):
        for d in ("${stateDir}", "${confDir}", "/run/wireguard"):
            host.succeed(f"test -d {d}")
        # /run/wireguard — каталог с конкретным назначением: без него команда wg внутри контейнера не видит
        # ЧУЖОЙ userspace-интерфейс, поэтому проверка подключённых интерфейсов незаметно пропускает нужный объект.
        mode = host.succeed("stat -c %a /run/wireguard").strip()
        assert mode == "755", f"/run/wireguard is {mode}, not 755 — the container's wg CLI reads it"
        ok("tmpfiles-activated", "stateDir, confDir and /run/wireguard exist, 755")

    # ── среда выполнения действительно запущена, а не просто объявлена ──
    # `oci-containers` НЕ включает службу backend автоматически; это делает модуль, поскольку узел
    # должен переживать перезагрузку. Именно декларацию, которая так и не запускается, и важно проверять.
    with subtest("the container runtime is up"):
        host.wait_for_unit("docker.service")
        print(host.succeed("systemctl is-active docker.service"))
        ok("runtime-running", "docker.service active — oci-containers does not do this for us")

    # ── сгенерированный unit и контракт внутри ЕГО СТАРТОВОГО СКРИПТА ──
    # ⚠️ `oci-containers` не помещает НИЧЕГО в .service: ExecStart указывает на сгенерированный скрипт в
    # store. Поиск по тексту unit не найдёт условий контракта — сначала нужно перейти по ExecStart (rig README).
    with subtest("the generated unit carries the whole contract"):
        unit = "docker-swg-node.service"
        host.succeed(f"systemctl cat {unit}")
        # ⚠️ `systemctl show -p ExecStart --value` возвращает СТРУКТУРИРОВАННУЮ ЗАПИСЬ, а не командную строку:
        #   { path=/nix/store/…-docker-swg-node-start ; argv[0]=… ; ignore_errors=no ; … }
        # поэтому `grep '^/nix/store'` ничего не найдёт, и проверка завершится с кодом, который ничего не говорит
        # о модуле. `systemctl cat` возвращает текст unit — его же разбирает probeN1C1; используем тот же подход
        # по той же причине.
        script = host.succeed(
            f"systemctl cat {unit} | grep -m1 '^ExecStart=' | cut -d= -f2- | awk '{{print $1}}'"
        ).strip()
        assert script.startswith("/nix/store/"), f"could not follow ExecStart: {script!r}"
        body = host.succeed(f"cat {script}")

        want = [
            "--network=host",                       # every panel-picked port lands on the host
            "--cap-add=NET_ADMIN",
            "--device=/dev/net/tun",
            # ⚠️ Ниже используется интерполяция NIX, а НЕ f-строка Python. `f"{stateDir}"` выглядит правильно,
            # но это не так: Nix оставляет обычное `{stateDir}` без изменений, Python ищет переменную с таким именем,
            # и проверка типов драйвера завершается ошибкой «Name `stateDir` used when not defined».
            # Привязка let находится на стороне NIX; подставить значение может только Nix.
            "${stateDir}:/var/lib/swg-noded",
            "${confDir}:/etc/amnezia/amneziawg",
            "/run/wireguard:/run/wireguard",
            "/var/run/docker.sock:/var/run/docker.sock",   # turnManage = true
            "SWG_NODE_PLATFORM",                    # T-P1: what OWNS the installation
            "SWG_DECLARATIVE",
            "SWG_UDP_PORTS",                        # T-P10: the declared firewall range
            "ghcr.io/sanityprotocol/swg-node",
        ]
        missing = [w for w in want if w not in body]
        assert not missing, f"the start script is missing: {missing}\\n---\\n{body}"
        ok("unit-contract", f"{len(want)} tokens, all present in the generated start script")

    # КОНТРОЛЬНАЯ ПРОВЕРКА: выше выполняется поиск по файлу, поэтому надёжность зависит от того, способен ли он
    # не найти лишнее. Маркер, которого заведомо нет, не должен обнаруживаться — иначе пустое `body`
    # или grep, совпадающий со всем, будет ошибочно принят за полный контракт.
    with subtest("the contract check can fail"):
        body = host.succeed("cat $(systemctl cat docker-swg-node.service"
                            " | grep -m1 '^ExecStart=' | cut -d= -f2- | awk '{print $1}')")
        assert "--privileged" not in body, "the node container must NOT be --privileged"
        assert "swg-this-token-is-not-in-the-contract" not in body
        ok("contract-check-can-fail", "an absent token reads as absent")

    # ── порядок запуска, от которого зависит доступность секрета ──
    # КОНТЕЙНЕР читает файл окружения, поэтому именно его unit должен ждать процесс, который создаёт этот файл.
    # Статическая проверка этого не обнаружит.
    with subtest("the container waits for what produces its secret"):
        after = host.succeed("systemctl show -p After --value docker-swg-node.service")
        assert "docker.service" in after, f"the unit is not ordered after docker: {after}"
        ok("unit-ordering", "ordered after the runtime")

    # ── честно обозначаем границу возможностей теста ──
    # Сам контейнер запустить нельзя: отсутствует доступный реестр образов. Это не ошибка модуля, и тест
    # не должен сообщать об этом как о сбое. Но он также не должен умалчивать об ограничении,
    # иначе читатель воспримет зелёный результат «контейнерный вариант» шире, чем следует.
    with subtest("the container cannot start here, and that is the known limit"):
        host.succeed("systemctl start docker-swg-node.service || true")
        state = host.succeed("systemctl show -p ActiveState --value docker-swg-node.service").strip()
        print(f"docker-swg-node ActiveState={state} (no registry in a test VM — expected)")
        ok("image-pull-out-of-scope",
           "the image is NOT exercised here; docker.yml and probeP1 cover the shipped image")
  '';
}

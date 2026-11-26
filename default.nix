# Пользователи канала (без flake) получают те же выходы, что и flake, с версиями,
# закреплёнными в flake.lock (D1):
#     nix-build -A packages.x86_64-linux.default
#     (import ./.).nixosModules.swg-node        # после добавления T-N8/T-N9
(import
  (
    let lock = builtins.fromJSON (builtins.readFile ./flake.lock); in
    fetchTarball {
      url = "https://github.com/edolstra/flake-compat/archive/${lock.nodes.flake-compat.locked.rev}.tar.gz";
      sha256 = lock.nodes.flake-compat.locked.narHash;
    }
  )
  { src = ./.; }
).defaultNix

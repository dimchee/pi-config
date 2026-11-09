{
  description = "Camoufox Test — fully Nix-packaged";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs =
    { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      lib = pkgs.lib;

      # Pinned browser release (see https://github.com/daijro/camoufox/releases)
      camoufoxVersion = "152.0.4-beta.28";
      camoufoxFullVersion = "152.0.4-beta.28-924f3109";

      # Libraries hard-required by the Camoufox browser binary (DT_NEEDED),
      # verified against `ldd libxul.so` of the fetched browser.
      runtimeLibs = with pkgs; [
        stdenv.cc.cc.lib # libstdc++.so.6 / libgcc_s.so.1

        # GTK3 stack
        gtk3
        glib
        gdk-pixbuf
        atk
        pango
        cairo

        # X11
        libx11
        libxcb
        libxcomposite
        libxcursor
        libxdamage
        libxext
        libxfixes
        libxi
        libxrandr
        libxrender

        # Media / misc
        alsa-lib
        nss
        nspr
        dbus
        fontconfig
        freetype
        mesa # OpenGL/EGL, dlopened for WebGL
        libdrm # dlopened for GPU paths
      ];

      # The `camoufox` Python package (not in nixpkgs) and its PyPI deps.
      camoufoxPkg = pkgs.python313.pkgs.buildPythonPackage rec {
        pname = "camoufox";
        version = "0.5.5";
        pyproject = true;

        src = pkgs.fetchPypi {
          inherit pname version;
          hash = "sha256-GLerf4Ry77KojnI1gmWqPrV669f4fZO9+oZW3KtwNbo=";
        };

        build-system = with pkgs.python313.pkgs; [ poetry-core ];

        dependencies = with pkgs.python313.pkgs; [
          browserforge
          geoip2 # [geoip] extra, always enabled here
          inquirer
          language-tags
          lxml
          numpy
          orjson
          platformdirs
          playwright
          pysocks
          pyyaml
          requests
          rich
          rich-click
          screeninfo
          typing-extensions
          ua-parser
        ];

        # nixpkgs has browserforge 1.2.3, upstream demands >=1.2.4,<2
        pythonRelaxDeps = [
          "browserforge"
          "playwright"
        ];

        doCheck = false;
      };

      pythonEnv = pkgs.python313.withPackages (
        ps: [
          camoufoxPkg
          ps.pytest
          ps.pytest-asyncio
          ps.hypothesis
        ]
      );

      # Browser binaries + uBlock Origin addon + GeoIP databases,
      # fetched once at build time into the Nix store (fixed-output derivation).
      camoufox-data = pkgs.stdenv.mkDerivation {
        name = "camoufox-data-${camoufoxVersion}";

        nativeBuildInputs = [ pythonEnv ];

        buildCommand = ''
          export XDG_CACHE_HOME=$TMPDIR/cache
          mkdir -p "$XDG_CACHE_HOME"

          camoufox sync
          camoufox fetch ${camoufoxVersion}

          installed="$XDG_CACHE_HOME/camoufox"
          test -d "$installed/browsers" || { echo "fetch failed"; exit 1; }

          mkdir -p $out
          # Only ship immutable data; volatile files (config.json,
          # repo_cache.json) are generated at runtime.
          mv "$installed/browsers" $out/
          if [ -d "$installed/addons" ]; then mv "$installed/addons" $out/; fi
          if [ -d "$installed/geoip"  ]; then mv "$installed/geoip"  $out/; fi
          touch $out/.0.5_FLAG      # compat marker, prevents auto-wipe
        '';

        outputHashAlgo = "sha256";
        outputHashMode = "recursive";
        outputHash = "sha256-HFvfPE9cMl2dwLBGRF6qvZn79iG+mra0moFf3rMHwUs=";
      };
      shellHook = ''
        # Bootstrap store data for interactive use too
        cacheDir="''${XDG_CACHE_HOME:-$HOME/.cache}/camoufox"
        mkdir -p "$cacheDir"
        for entry in browsers addons geoip .0.5_FLAG; do
          rm -rf "$cacheDir/$entry"
          ln -s "${camoufox-data}/$entry" "$cacheDir/$entry"
        done
        if [ ! -f "$cacheDir/config.json" ]; then
          printf '{"active_version": "browsers/official/${camoufoxFullVersion}"}\n' \
            > "$cacheDir/config.json"
        fi
      '';

      # Runnable applications: bootstraps ~/.cache/camoufox with symlinks to
      # the store data (the Python package hardcodes that path), then runs
      # the CLI / server module from this repo.
      mkWrapper = name: module:
        pkgs.writeShellScriptBin name ''
          set -eu
          export LD_LIBRARY_PATH="${lib.makeLibraryPath runtimeLibs}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
          ${shellHook}
          export PYTHONPATH="${./.}''${PYTHONPATH:+:$PYTHONPATH}"
          exec "${pythonEnv}/bin/python" -m ${module} "$@"
        '';
      cam = mkWrapper "cam" "camoufox_tool.cli";
      camoufox-server = mkWrapper "camoufox-server" "camoufox_tool.server";
    in
    {
      packages.${system} = {
        default = cam;
        inherit cam camoufox-server camoufox-data;
      };
      apps.${system}.default = {
        type = "app";
        program = "${cam}/bin/cam";
      };
      devShells.${system}.default = pkgs.mkShell {
        packages = [ pythonEnv ] ++ runtimeLibs;
        env.LD_LIBRARY_PATH = lib.makeLibraryPath runtimeLibs;
        shellHook = shellHook;
      };
    };
}

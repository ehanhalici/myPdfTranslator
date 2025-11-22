{ pkgs ? import <nixpkgs> {} }:

let
  libs = [
    pkgs.gcc.cc.lib
    pkgs.zlib 
    pkgs.stdenv.cc.cc.lib

  ];
in
pkgs.mkShell {
  buildInputs = [
    pkgs.uv
    pkgs.python312
    pkgs.python312Packages.pyqt5
    pkgs.python312Packages.pyqt5-sip
    pkgs.qt5.qtbase

  ] ++ libs;

  shellHook = ''
    for lib in ${pkgs.lib.concatStringsSep " " (map (p: "${p}/lib") libs)};
    do
      export LD_LIBRARY_PATH="$lib:$LD_LIBRARY_PATH"
    done

    # Qt plugin yolunu ayarla
    export QT_QPA_PLATFORM_PLUGIN_PATH="${pkgs.qt5.qtbase.bin}/lib/qt-${pkgs.qt5.qtbase.version}/plugins/platforms";

    echo "export LD_LIBRARY_PATH=$LD_LIBRARY_PATH" >> .venv/bin/activate
    echo "export QT_QPA_PLATFORM_PLUGIN_PATH=$QT_QPA_PLATFORM_PLUGIN_PATH" >> .venv/bin/activate
    source .venv/bin/activate                                                  
  '';
}

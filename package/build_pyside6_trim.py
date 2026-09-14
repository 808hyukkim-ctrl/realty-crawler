"""PyInstaller spec 공용: PySide6 용량 최적화.

이 프로젝트 앱들은 Qt 중 QtCore/QtGui/QtWidgets 만 사용한다.
`collect_all('PySide6')` 로 통째로 넣으면 QtWebEngineCore(약 193MB) 등 안 쓰는
모듈까지 포함돼 빌드가 300MB 를 넘고 빌드도 느려진다.

그래서 PySide6 는 PyInstaller 자동 훅(실제 import 된 QtCore/QtGui/QtWidgets 만
수집)에 맡기고, 아래에서 (1) 안 쓰는 Qt 파이썬 모듈을 import 그래프에서 제외하고
(2) 자동 훅이 넣더라도 대용량 미사용 DLL 은 이름으로 걸러낸다.

주의: pandas/numpy/openpyxl 은 이 앱이 실제로 쓰므로(엑셀 출력) 제외하지 않는다.
검증됨: auto_collector.spec 이 동일 방식으로 61MB 로 정상 동작.
"""
import os

# (1) import 그래프에서 빼는 미사용 Qt 파이썬 모듈. Analysis(excludes=...) 에 더해 쓴다.
PYSIDE6_UNUSED_QT = [
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
    'PySide6.QtWebChannel', 'PySide6.QtWebSockets', 'PySide6.QtWebView',
    'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
    'PySide6.QtQml', 'PySide6.QtQmlModels',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtSpatialAudio',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets',
    'PySide6.QtDesigner', 'PySide6.QtUiTools', 'PySide6.QtHelp',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDBus',
    'PySide6.QtPositioning', 'PySide6.QtLocation', 'PySide6.QtBluetooth',
    'PySide6.QtSerialPort', 'PySide6.QtSerialBus', 'PySide6.QtSensors', 'PySide6.QtNfc',
    'PySide6.QtPrintSupport', 'PySide6.QtScxml', 'PySide6.QtStateMachine',
    'PySide6.QtRemoteObjects', 'PySide6.QtHttpServer', 'PySide6.QtTextToSpeech',
    'PySide6.QtVirtualKeyboard', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets',
    'PySide6.QtNetworkAuth',
]

# (2) 자동 훅이 넣더라도 이름으로 확실히 빼는 대용량 미사용 DLL.
_DROP_DLL_KEYWORDS = (
    'qt6webengine', 'qt6quick', 'qt6qml', 'qt63d', 'qt6pdf', 'qt6charts',
    'qt6datavisualization', 'qt6graphs', 'qt6designer', 'qt6multimedia', 'qt6opengl',
    'qt6sql', 'qt6dbus', 'qt6virtualkeyboard', 'qt6svg', 'qt6spatialaudio',
    'opengl32sw', 'd3dcompiler',
    'avcodec', 'avformat', 'avutil', 'swscale', 'swresample',
)


def drop_heavy_qt_binaries(binaries):
    """a.binaries 리스트에서 대용량 미사용 Qt/멀티미디어 DLL 을 제거한 리스트를 돌려준다."""
    def _keep(item):
        name = os.path.basename(item[0]).lower()
        return not any(k in name for k in _DROP_DLL_KEYWORDS)

    return [b for b in binaries if _keep(b)]

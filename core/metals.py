from . decorations import handle_decorations
from . handle_execute_client import handle_execute_client
from . handle_input_box import handle_input_box
from . status import handle_status
from .. commands.lsp_metals_text_command import LspMetalsTextCommand
from distutils.version import LooseVersion
from LSP.plugin import AbstractPlugin
from LSP.plugin import ClientConfig
from LSP.plugin import Request as LspRequest
from LSP.plugin import WorkspaceFolder
from LSP.plugin.core.protocol import Position, Response
from LSP.plugin.core.typing import Optional, Any, List
from LSP.plugin.core.views import first_selection_region
from LSP.plugin.core.views import Point
from LSP.plugin.core.views import point_to_offset
from LSP.plugin.core.views import region_to_range
from urllib.request import urlopen, Request
import json

import sublime
import os

_COURSIER_PATH = os.path.join(os.path.dirname(__file__), '..', 'coursier')
_LATEST_STABLE = "latest-stable"
_LATEST_SNAPSHOT = "latest-snapshot"
_LATEST_STABLE_ARTIFACT = "latest.stable"

_SETTINGS_BASENAME = "LSP-metals.sublime-settings"

class Metals(AbstractPlugin):

    @classmethod
    def name(cls) -> str:
        return LspMetalsTextCommand.session_name

    @classmethod
    def can_start(
        cls,
        window: sublime.Window,
        initiating_view: sublime.View,
        workspace_folders: List[WorkspaceFolder],
        configuration: ClientConfig
    ) -> Optional[str]:
        if not workspace_folders:
            return "No workspace detected. Try opening your project at the workspace root."

        plugin_settings = sublime.load_settings(_SETTINGS_BASENAME)
        java_path = get_java_path(plugin_settings)
        if not java_path :
            return "Please install java or set the 'java_home' setting"

        server_version = plugin_settings.get('server_version', _LATEST_STABLE)

        if server_version == _LATEST_SNAPSHOT:
            try:
                httprequest = Request(
                    "https://scalameta.org/metals/latests.json",
                    headers={"Accept": "application/json"},
                    method="GET"
                )
                httpresponse = urlopen(httprequest)
                body = json.loads(httpresponse.read().decode())
                server_version = body.get("snapshot")
            except:
                return "Couldn't get latest version number from scalameta website, please set the 'server_version'"
        elif not server_version or server_version == _LATEST_STABLE:
            server_version = _LATEST_STABLE_ARTIFACT

        properties = prepare_server_properties(plugin_settings.get("server_properties"))
        command = create_launch_command(java_path, server_version, properties)
        configuration.command = command
        return None

    def on_pre_send_request_async(self, request_id: int, request: LspRequest) -> None:
        if request.method == 'textDocument/hover' and request.view:
            session = self.weaksession()
            if not session:
                return
            if not session.get_capability('experimental.rangeHoverProvider'):
                return
            view = request.view
            region = first_selection_region(view)
            if region is not None:
                position = request.params['position']  # type: Position
                point = point_to_offset(Point.from_lsp(position), view)
                if region.contains(point):
                    request.params['range'] = region_to_range(view, region)

    def on_server_response_async(self, method: str, response: Response) -> None:
        if method == "textDocument/completion" and sublime.load_settings(_SETTINGS_BASENAME).get("rationalise_completions", False):
            for item in response.result['items']:
                label = item['label'].strip()
                detail = item['detail'].strip()
                if label.endswith(detail):
                    item['label'] = label[:-len(detail)] or label
                if detail.startswith(": "):
                    item['detail'] = detail[2:] or detail

    # notification and request handlers

    def m_metals_status(self, params: Any) -> None:
        session = self.weaksession()
        if not session:
            return
        handle_status(session, params)

    def m_metals_publishDecorations(self, decorationsParams: Any) -> None:
        session = self.weaksession()
        if not session:
            return
        handle_decorations(session, decorationsParams)

    def m_metals_executeClientCommand(self, params: Any) -> None:
        session = self.weaksession()
        if not session:
            return

        handle_execute_client(session, params)

    def m_metals_inputBox(self, params: Any, request_id: Any) -> None:
        session = self.weaksession()
        if not session:
            return
        handle_input_box(session, params, request_id)


def get_java_path(settings: sublime.Settings) -> str:
    java_home = settings.get("java_home")
    if isinstance(java_home, str) and java_home:
        return os.path.join(java_home, "bin", "java")
    java_home = os.environ.get('JAVA_HOME')
    if java_home:
        return os.path.join(java_home, "bin", "java")
    return "java"


def create_launch_command(java_path: str, artifact_version: str, server_properties: List[str]) -> List[str]:
    binary_version = "2.12"
    if artifact_version == _LATEST_STABLE_ARTIFACT or LooseVersion(artifact_version) > LooseVersion("0.11.2"):
        binary_version = "2.13"

    return [java_path] + server_properties + [
        "-jar",
        _COURSIER_PATH,
        "launch",
        "--ttl",
        "Inf",
        "--repository",
        "bintray:scalacenter/releases",
        "--repository",
        "sonatype:snapshots",
        "--main-class",
        "scala.meta.metals.Main",
        "org.scalameta:metals_{}:{}".format(binary_version, artifact_version)
    ]


def prepare_server_properties(properties: List[str]) -> List[str]:
    stripped = map(lambda p: p.strip(), properties)
    none_empty = list(filter(None, stripped))
    return none_empty

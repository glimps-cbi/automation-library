from glimps.base import GlimpsAction
from glimps.models import SubmitArgument, SubmitResponse
from glimps.models import WaitForResultArgument, AnalysisResponse


class SubmitFileToBeAnalysed(GlimpsAction):
    """Action to submit a file for glimps malware analysis"""

    name = "Analyse a file"
    description = "Submit file to Glimps Detect to be analysed"
    results_model = SubmitResponse

    def run(self, arguments: SubmitArgument) -> SubmitResponse:
        # send the request to Glimps
        uuid = self.gdetect_client.push(
            self._data_path.joinpath(arguments.file_name),
            bypass_cache=arguments.bypass_cache,
            tags=arguments.user_tags,
            timeout=arguments.push_timeout,
            description=arguments.description,
            archive_password=arguments.archive_pwd,
        )
        response = SubmitResponse(status=True, uuid=uuid)
        return response


class SubmitFileWaitForResult(GlimpsAction):
    """Action to submit a file to GLIMPS Detect and wait for a result"""

    name = "Analyse a file and wait for result"
    description = "Submit file to Glimps Detect to be analysed and wait for its results"
    results_model = AnalysisResponse

    def run(self, arguments: WaitForResultArgument) -> AnalysisResponse:
        analysis = self.gdetect_client.waitfor(
            self._data_path.joinpath(arguments.file_name),
            bypass_cache=arguments.bypass_cache,
            pull_time=arguments.pull_time,
            push_timeout=arguments.push_timeout,
            timeout=arguments.timeout,
            tags=arguments.user_tags,
            description=arguments.description,
            archive_password=arguments.archive_pwd,
        )
        response: AnalysisResponse = AnalysisResponse.parse_obj(analysis)

        return response
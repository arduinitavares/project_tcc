"""Public spec-related service boundaries."""

from services.specs.compiler_service import (
    check_spec_authority_status,
    compile_spec_authority,
    compile_spec_authority_for_version,
    ensure_accepted_spec_authority,
    ensure_spec_authority_accepted,
    get_compiled_authority_by_version,
    load_compiled_artifact,
    preview_spec_authority,
    update_spec_and_compile_authority,
)
from services.specs.lifecycle_service import (
    approve_spec_version,
    link_spec_to_product,
    read_project_specification,
    register_spec_version,
    save_project_specification,
)
from services.specs.story_validation_service import (
    compute_story_input_hash,
    validate_story_with_spec_authority,
)

__all__: list[str] = [
    "approve_spec_version",
    "check_spec_authority_status",
    "compile_spec_authority",
    "compile_spec_authority_for_version",
    "compute_story_input_hash",
    "ensure_accepted_spec_authority",
    "ensure_spec_authority_accepted",
    "get_compiled_authority_by_version",
    "link_spec_to_product",
    "load_compiled_artifact",
    "preview_spec_authority",
    "read_project_specification",
    "register_spec_version",
    "save_project_specification",
    "update_spec_and_compile_authority",
    "validate_story_with_spec_authority",
]

from sqlalchemy.orm import configure_mappers

from app.db.models import AnalysisRun, AnalysisRunCollectionRun


def test_analyzer_mappers_do_not_require_control_plane_models():
    # The analyzer shares these tables but intentionally does not import the
    # Control Plane ORM. Mapper configuration must therefore remain independent.
    configure_mappers()
    assert AnalysisRun.__tablename__ == "analysis_runs"
    assert AnalysisRunCollectionRun.__tablename__ == "analysis_run_collection_runs"


def test_external_control_plane_ids_are_scalar_orm_columns():
    assert not AnalysisRun.__table__.c.project_id.foreign_keys
    assert not AnalysisRun.__table__.c.collection_run_id.foreign_keys
    assert not AnalysisRunCollectionRun.__table__.c.collection_run_id.foreign_keys
    assert AnalysisRunCollectionRun.__table__.c.analysis_run_id.foreign_keys

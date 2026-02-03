from app.db import Job, JobStatus, apply_transition, is_valid_transition


def test_valid_transitions_sequence():
    job = Job(id="job1")
    assert job.status == JobStatus.queued
    apply_transition(job, JobStatus.extracting)
    apply_transition(job, JobStatus.scripting)
    apply_transition(job, JobStatus.tts)
    apply_transition(job, JobStatus.syncing)
    apply_transition(job, JobStatus.done)
    assert job.status == JobStatus.done


def test_invalid_transition_rejected():
    job = Job(id="job2")
    assert not is_valid_transition(JobStatus.queued, JobStatus.done)
    try:
        apply_transition(job, JobStatus.done)
        assert False, "Expected ValueError for invalid transition"
    except ValueError:
        assert job.status == JobStatus.queued

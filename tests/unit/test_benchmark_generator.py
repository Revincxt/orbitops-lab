from orbitops.benchmarking import generate_scenario, generate_scenarios

from tests.factories import make_benchmark_spec


def test_scenario_generation_is_byte_model_reproducible() -> None:
    spec = make_benchmark_spec()

    first, first_descriptor = generate_scenario(spec, "tiny", "medium", 0)
    second, second_descriptor = generate_scenario(spec, "tiny", "medium", 0)

    assert first == second
    assert first_descriptor == second_descriptor
    assert first_descriptor.task_count == 6
    assert first.metadata["generator_seed"] == first_descriptor.generator_seed


def test_matrix_generation_has_stable_order_and_unique_scenarios() -> None:
    spec = make_benchmark_spec(
        sizes=("tiny", "small"),
        difficulties=("easy", "hard"),
    )

    generated = generate_scenarios(spec)
    identities = [descriptor.scenario_id for _, descriptor in generated]

    assert len(generated) == 4
    assert identities == [
        "test-benchmark-tiny-easy-000",
        "test-benchmark-tiny-hard-000",
        "test-benchmark-small-easy-000",
        "test-benchmark-small-hard-000",
    ]
    assert len(set(identities)) == len(identities)

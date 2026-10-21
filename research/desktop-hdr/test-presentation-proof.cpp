#include "presentation-proof.h"
#include <cassert>

// Exercise the actual gate with a deterministic clock and a fake Vulkan wait.
// No display or GPU is needed; a queued frame alone never enters this gate.
int main()
{
    using Clock = std::chrono::steady_clock;
    const auto deadline = Clock::time_point(std::chrono::seconds(10));
    for (int scenario = 0; scenario != 5; ++scenario) {
        auto now = Clock::time_point{};
        if (scenario == 3) now = deadline;
        if (scenario == 4) now = deadline + std::chrono::nanoseconds(1);
        int waits = 0, markers = 0;
        bool failed = false;
        try {
            requirePresentationCompletion([&](std::uint64_t timeout) {
                ++waits;
                assert(timeout == 10000000000ULL); // finite remaining budget
                if (scenario == 2) now = deadline; // rounded / late success
                return scenario != 1; // timeout, suboptimal, or API failure
            }, [&] { return now; }, deadline);
            ++markers; // same position as FIRST_PRESENT_OK in the renderer
        } catch (const std::runtime_error&) {
            failed = true;
        }
        assert(markers == (scenario == 0 ? 1 : 0));
        assert(failed == (scenario != 0));
        assert(waits == (scenario >= 3 ? 0 : 1));
    }
    // Time already spent acquiring/rendering reduces the completion budget.
    auto now = deadline - std::chrono::nanoseconds(7);
    requirePresentationCompletion([](std::uint64_t timeout) {
        assert(timeout == 7);
        return true;
    }, [&] { return now; }, deadline);
}

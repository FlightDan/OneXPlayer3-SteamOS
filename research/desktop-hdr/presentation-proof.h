#pragma once
#include <chrono>
#include <cstdint>
#include <stdexcept>

// The caller maps only VK_SUCCESS from vkWaitForPresentKHR to true. Queueing a
// present, rendering completion, timeout, and suboptimal/out-of-date results do
// not establish the trial's presentation-completion gate.
template<class Wait, class Now>
void requirePresentationCompletion(Wait wait, Now now,
                                   std::chrono::steady_clock::time_point deadline)
{
    const auto remaining = std::chrono::duration_cast<std::chrono::nanoseconds>(deadline - now()).count();
    if (remaining <= 0)
        throw std::runtime_error("HDR trial expired before presentation completion wait");
    if (!wait(static_cast<std::uint64_t>(remaining)))
        throw std::runtime_error("HDR trial presentation completion failed or timed out");
    // Vulkan permits implementation timeout rounding. A late success must not
    // open confirmation; the independent recovery guard retains its own clock.
    if (now() >= deadline)
        throw std::runtime_error("HDR trial expired during presentation completion wait");
}

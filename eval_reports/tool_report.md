# Tool Invocation Evaluation Report

## Metrics
- **Correct Tool Rate:** 100.00%
- **Correct Args Rate:** 100.00%
- **False Positive Rate:** 0.00%

## Utterance Details
| Utterance | Expected Tool | Success | Response Snapshot |
|-----------|---------------|---------|-------------------|
| My phone number is 0300-1234567. | update_user_info | ✅ | Your phone number has been updated to 0300-1234567.... |
| Update my email to ahmed@example.com | update_user_info | ✅ | Your email address has been updated to ahmed@example.com.... |
| What is my phone number? | get_user_info | ✅ | I don't have a phone number for you.... |
| How much for a standard room from 2026-06-01 to 2026-06-04? | calculate_room_cost | ✅ | Your 3-night stay in a Standard room will cost $210.00.... |
| Cost of suite for 7 nights starting 2026-06-01 to 2026-06-08? | calculate_room_cost | ✅ | Your 7-night stay in a Suite room will cost $2100.00.... |
| Book me a standard room from 2026-06-01 to 2026-06-05 | add_booking_to_calendar | ✅ | Your booking has been added to the calendar for 2026-06-01 t... |
| I want to reserve a deluxe room starting 2026-10-10 until 2026-10-12 | add_booking_to_calendar | ✅ | Your booking has been added to the calendar for 2026-10-10 t... |
| What's the weather like in Islamabad on 2026-05-07? | get_hotel_weather | ✅ | Forecast for Islamabad on 2026-05-07: clear sky, around 23.6... |
| Will it rain tomorrow in Lahore on 2026-05-08? | get_hotel_weather | ✅ | Forecast for Islamabad on 2026-05-08: clear sky, around 24.8... |
| Hi, how are you? | None | ✅ | Hi there! How can I assist you today?... |
| What are the hotel policies? | None | ✅ | Sure, here are some of our key policies:  1. **Room Assignme... |
| Is the swimming pool open? | None | ✅ | The outdoor pool is open daily from 07:00 to 21:00. Would yo... |

## Backend Unit Test Results
| Test Name | Outcome | Duration (s) |
|-----------|---------|--------------|
| `test_create_guest` | ✅ PASSED | 0.038 |
| `test_read_guest` | ✅ PASSED | 0.031 |
| `test_update_guest` | ✅ PASSED | 0.043 |
| `test_delete_or_overwrite` | ✅ PASSED | 0.030 |
| `test_crm_with_invalid_id` | ✅ PASSED | 0.001 |
| `test_single_room_cost` | ✅ PASSED | 0.005 |
| `test_suite_cost` | ✅ PASSED | 0.001 |
| `test_invalid_room_type` | ✅ PASSED | 0.001 |
| `test_zero_nights` | ✅ PASSED | 0.001 |
| `test_create_booking` | ✅ PASSED | 0.034 |
| `test_booking_content` | ✅ PASSED | 0.039 |
| `test_duplicate_booking` | ✅ PASSED | 0.047 |
| `test_weather_valid_location` | ✅ PASSED | 2.274 |
| `test_weather_invalid_location` | ✅ PASSED | 1.072 |

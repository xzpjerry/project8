import arrow
from enum import Enum
from math import ceil


class event_compare_result(Enum):
    within = 0
    without = 1


class calendar_event(object):

    def __init__(self, start, end):
        self.flag = False
        self.start = arrow.get(start).to('local')
        self.start_time = arrow.get(self.start.format("HH:mm:ss"), "HH:mm:ss")

        self.end = arrow.get(end).to('local')
        self.end_time = arrow.get(self.end.format("HH:mm:ss"), "HH:mm:ss")

        self.start_timestamp = self.start.timestamp
        self.end_timestamp = self.end.timestamp

        self.duration = (self.end - self.start).total_seconds()
        self.time_duration = (self.end_time - self.start_time).total_seconds()

        if self.duration >= 86400:
            self.flag = True
        if self.time_duration < 0:  # prepare for time range setting like 23:00 ~ 1:00
            self.end_time = self.end_time.shift(days=1)
            self.time_duration = (
                self.end_time - self.start_time).total_seconds()

    def __str__(self):
        result = "(Start: %s    " % self.start
        result += "End: %s    " % self.end
        result += "Duration: %ss, from %s to %s    );" % (self.duration, self.start_time.format("HH:mm:ss"), self.end_time.format("HH:mm:ss"))
        return result

    def compare_to(self, eventB):
        if eventB.start >= self.end:
            return event_compare_result.without

        if self.flag:  # self has more than 1 day, it must be on our range
            return event_compare_result.within  # self is within eventB

        if self.start_time >= eventB.end_time or eventB.start_time >= self.end_time:
            return event_compare_result.without  # self is without range

        return event_compare_result.within


class eventrange(calendar_event):

    def __init__(self, start, end):
        super(eventrange, self).__init__(start, end)
        self.blockage = []

    def __str__(self):
        result = super(eventrange, self).__str__()
        if self.blockage:
            result += "Blockage in Range: "
            for block in self.blockage:
                result += " "
                result += str(block)
            result += "\nFree time:"
            if self.free:
                for freetime in self.free:
                    result += str(arrow.get(freetime[0]).to('local'))
                    result += " ~ "
                    result += str(arrow.get(freetime[1]).to('local'))
                    result += " ; "
            else:
                result += "None."
        return result

    def subtract_blockage(self):  # for range instance only

        if self.blockage:
            accurate_subranges = {}

            days = ceil(self.duration / 86400)
            for day in range(days + 1):
                thisdays_start = self.start_timestamp + day * 86400
                thisdays_end = thisdays_start + int(self.time_duration)
                for i in range(thisdays_start, thisdays_end + 1):
                    accurate_subranges[i] = True

            for block in self.blockage:
                for i in range(block.start_timestamp, block.end_timestamp + 1):
                    if accurate_subranges.get(i):
                        accurate_subranges[i] = False

            if accurate_subranges[self.start_timestamp]:
                last_free_start = self.start_timestamp
            else:
                last_free_start = None

            self.free = []
            day_counter = 0
            for i in accurate_subranges:
                if last_free_start and accurate_subranges[i] == False:
                    self.free.append((last_free_start, i))
                    last_free_start = None
                elif (last_free_start == None) and accurate_subranges[i]:
                    last_free_start = i
                if day_counter == self.time_duration:
                    if last_free_start:
                        self.free.append((last_free_start, i))
                    day_counter = 0
                day_counter += 1

'''
a = eventrange('2017-11-15T16:01:54.587619-08:00',
               '2017-11-23T00:01:54.587619-08:00')
b = calendar_event('2017-11-16T16:01:54.587619-08:00',
                   '2017-11-16T19:01:55.587619-08:00')
print(b.compare_to(a))
a.blockage.append(b)
a.subtract_blockage()
print(a)
b = calendar_event('2017-11-13T13:20:24.889989-08:00',
                   '2017-11-14T16:20:24.889989-08:00')
print(b.compare_to(a))

'''

'''
import random
range_day = 7
range_hour = 8

now = arrow.now()

now_min = now.format("mm")
now_hour = int(now.format('HH'))
then = now.shift(days=range_day, hours=range_hour)

then_min = then.format("mm")
RANGE = eventrange(now.isoformat(), then.isoformat())

def test_within():

    test_case_start = now.shift(days=1)
    test_case_end = test_case_start.shift(seconds=1)
    test_case = calendar_event(test_case_start, test_case_end)
    assert test_case.compare_to(RANGE) == event_compare_result.within

    test_case_start = now.shift(hours=-3)
    test_case_end = test_case_start.shift(hours=4)
    test_case = calendar_event(test_case_start, test_case_end)
    assert test_case.compare_to(RANGE) == event_compare_result.within

    test_case_start = then.shift(days=-1)
    test_case_end = test_case_start.shift(days=2)
    test_case = calendar_event(test_case_start, test_case_end)
    assert test_case.compare_to(RANGE) == event_compare_result.within

    for i in range(10):
        test_case_start = now.shift(days=random.randrange(range_day))
        test_case_start = test_case_start.shift(hours=random.randrange(1, range_hour))
        test_case_end = test_case_start.shift(hours=1)

        test_case = calendar_event(test_case_start, test_case_end)
        assert test_case.compare_to(RANGE) == event_compare_result.within

        test_case_start = then.shift(days=random.randrange(-range_day, 0))
        test_case_start = test_case_end.shift(hours=random.randrange(1, range_hour))
        test_case_end = test_case_start.shift(hours=1)

        
        assert test_case.compare_to(RANGE) == event_compare_result.within
        RANGE.blockage.append(test_case)
        RANGE.subtract_blockage()
        print(RANGE)
        RANGE.blockage = []


test_within()
'''

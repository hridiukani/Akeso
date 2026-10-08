# boltons (excerpt): timeutils

This is the `timeutils` module of the [boltons](https://github.com/mahmoud/boltons)
library (BSD licence, see LICENSE). Among other helpers, `daterange(start, stop, step=1,
inclusive=False)` yields dates from `start` up to `stop`, like `range()` for dates. `step`
can be a number of days, a `timedelta`, or a `(years, months, days)` tuple:

```python
list(daterange(date(2020, 1, 31), date(2020, 4, 1), step=(0, 1, 0)))
```

## Bug report (upstream issue #319)

> **daterange with a step of months or years gives wrong dates**
>
> Stepping by one year from 2012-12-25 to 2016-01-01 should give
> 2012-12-25, 2013-12-25, 2014-12-25 and 2015-12-25, but that's not what I get.
> Stepping by 13 months from 2012-12-25 should give 2012-12-25, 2014-01-25 and 2015-02-25.
> Month steps that cross December seem to be the problem.

## Running the tests

```
python -m pytest
```

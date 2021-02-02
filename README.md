# Karton Dashboard

![](img/dashboard.png)

A small Flask application for Karton task and queue introspection.

**Author**: CERT.pl

**Maintainers**: msm

## Usage

First of all, make sure you have setup the core system: https://github.com/CERT-Polska/karton

Then install karton-dashboard from PyPi:

```shell
$ pip install karton-dashboard

$ karton-dashboard run -h 127.0.0.1 -p 5000
```

The `karton-dashboard` is just a wrapper on the `flask` program so you're free to provide it with arguments accepted by flask like `-h`, `--cert=path` and so on.

![Co-financed by the Connecting Europe Facility by of the European Union](https://www.cert.pl/wp-content/uploads/2019/02/en_horizontal_cef_logo-1.png)

@AccessControl.authorizationCheck: #NOT_REQUIRED
define view entity zi_joins as select from zt_one as o
  inner join zt_two as t on t.a = o.k or t.b = o.k
  left outer many to one join zt_one as s on s.k = s.k
  cross join zt_three as c
  right outer join zt_three as r on r.k = o.k
  inner many to one join zt_three as l on l.k like 'A%'
  association to zt_three as _Free on _Free.k = o.k
{
  key o.k as K
}
